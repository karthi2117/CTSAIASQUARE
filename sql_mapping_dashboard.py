import streamlit as st
import pandas as pd
import sqlparse
import re
from pathlib import Path
from sqlparse.sql import Identifier, Where, Comparison, Function
import os
import zipfile
import tempfile
from io import BytesIO
import json

class SQLMappingReviewer:
    def __init__(self, mapping_file_path=None, sql_folder_path=None):
        self.mapping_file = mapping_file_path
        self.sql_folder = sql_folder_path
        self.table_mappings = None
        self.column_mappings = None
        self.review_comments = []
        
        # Initialize SQL keywords to check
        self.sql_keywords = {
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'GROUP BY',
            'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET'
        }

    def load_mappings_from_dataframe(self, table_df, column_df):
        """Load mappings from uploaded DataFrames"""
        try:
            # Process table mappings
            self.table_mappings = table_df.copy()
            rename_columns = [i.strip() for i in self.table_mappings.columns]
            self.table_mappings.columns = rename_columns
            self.table_mappings = self.table_mappings.dropna(subset=['OldTableName', 'NewTableName'])
            
            # Clean whitespace from table names
            self.table_mappings['OldTableName'] = self.table_mappings['OldTableName'].str.strip()
            self.table_mappings['NewTableName'] = self.table_mappings['NewTableName'].str.strip()
            
            # Process column mappings
            self.column_mappings = column_df.copy()
            rename_columns = [i.strip() for i in self.column_mappings.columns]
            self.column_mappings.columns = rename_columns
            self.column_mappings = self.column_mappings.dropna(subset=['TableName', 'OldColumnName', 'NewColumnName'])
            
            # Clean whitespace from column mappings
            self.column_mappings['TableName'] = self.column_mappings['TableName'].str.strip()
            self.column_mappings['OldColumnName'] = self.column_mappings['OldColumnName'].str.strip()
            self.column_mappings['NewColumnName'] = self.column_mappings['NewColumnName'].str.strip()
            
            # Convert to dictionaries for faster lookup
            self.table_mappings = self.table_mappings.set_index('OldTableName')['NewTableName'].to_dict()
            self.column_mappings = self.column_mappings.groupby('TableName').apply(
                lambda x: x.set_index('OldColumnName')['NewColumnName'].to_dict(), include_groups=False
            ).to_dict()
            
            return True
        except Exception as e:
            self.review_comments.append(f"CRITICAL: Failed to load mappings - {str(e)}")
            return False

    def analyze_sql_content(self, sql_content, filename):
        """Analyze a single SQL content string"""
        file_comments = []
        
        # Phase 1: SQL Syntax Validation
        syntax_issues = self._validate_sql_structure(sql_content)
        file_comments.extend(syntax_issues)
        
        # Phase 2: Table/Column Mapping Checks
        mapping_issues = self._check_mappings(filename, sql_content)
        file_comments.extend(mapping_issues)
        
        # Phase 3: Advanced Semantic Checks
        semantic_issues = self._check_semantics(sql_content)
        file_comments.extend(semantic_issues)
        
        return file_comments

    def _validate_sql_structure(self, sql_content):
        """Validate basic SQL syntax using sqlparse"""
        issues = []
        try:
            parsed = sqlparse.parse(sql_content)
            if not parsed:
                issues.append("ERROR: Empty SQL file")
                return issues
                
            stmt = parsed[0]
            
            # Check for required clauses
            if "SELECT" not in sql_content.upper():
                issues.append("ERROR: Missing SELECT clause")
            if "FROM" not in sql_content.upper():
                issues.append("ERROR: Missing FROM clause")
                
            # Check for unbalanced parentheses
            if sql_content.count('(') != sql_content.count(')'):
                issues.append("ERROR: Unbalanced parentheses")
                
            return issues
        except Exception as e:
            return [f"CRITICAL: SQL Parsing Failed - {str(e)}"]

    def _check_mappings(self, filename, sql_content):
        """Check for table and column name mappings"""
        issues = []
        
        # Table-level checks
        for old_table, new_table in self.table_mappings.items():
            pattern = rf'(?<!\w){re.escape(old_table)}(?!\w)'
            if re.search(pattern, sql_content, re.IGNORECASE):
                issues.append(
                    f"TABLE MAPPING: '{old_table}' -> Should be '{new_table}'"
                )
        
        # Column-level checks
        for table in self.column_mappings:
            for old_col, new_col in self.column_mappings[table].items():
                patterns = [
                    rf'(?<!\w){re.escape(table)}\.{re.escape(old_col)}(?!\w)',
                    rf'(?<!\w){re.escape(old_col)}(?!\w)(?=.*?\bFROM\b.*?\b{table}\b)'
                ]
                if any(re.search(p, sql_content, re.IGNORECASE) for p in patterns):
                    issues.append(
                        f"COLUMN MAPPING: '{old_col}' -> Should be '{new_col}' (in table '{table}')"
                    )
        return issues

    def _check_semantics(self, sql_content):
        """Advanced checks using sqlparse tokens"""
        issues = []
        try:
            parsed = sqlparse.parse(sql_content)[0]
            
            # Check for explicit joins without ON clauses
            for token in parsed.tokens:
                if isinstance(token, Identifier) and 'JOIN' in token.normalized:
                    if 'ON' not in token.normalized:
                        issues.append("WARNING: JOIN without ON clause detected")
            
            # Check WHERE clause for potential issues
            where_clauses = [t for t in parsed.tokens if isinstance(t, Where)]
            for where in where_clauses:
                for comparison in where.get_sublists():
                    if isinstance(comparison, Comparison):
                        left = comparison.left.value.strip()
                        right = comparison.right.value.strip()
                        
                        # Check for implicit type casting
                        if ("'" in right and not any(kw in left.upper() for kw in ['DATE', 'TIME', 'TIMESTAMP'])):
                            issues.append(f"WARNING: Possible string-to-other type comparison: {left} = {right}")
        except:
            pass  # Skip semantic analysis if parsing fails
        
        return issues

    def apply_corrections(self, sql_content):
        """Apply table and column mappings to SQL content"""
        corrected_content = self._apply_table_mappings(sql_content)
        corrected_content = self._apply_column_mappings(corrected_content)
        return corrected_content

    def _apply_table_mappings(self, sql_content):
        """Apply table name mappings to SQL content"""
        corrected_content = sql_content
        
        for old_table, new_table in self.table_mappings.items():
            pattern = rf'\b{re.escape(old_table)}\b'
            corrected_content = re.sub(pattern, new_table, corrected_content, flags=re.IGNORECASE)
        
        return corrected_content

    def _apply_column_mappings(self, sql_content):
        """Apply column name mappings to SQL content"""
        corrected_content = sql_content
        
        old_to_new_tables = self.table_mappings
        new_to_old_tables = {v: k for k, v in old_to_new_tables.items()}
        
        for new_table_name in self.column_mappings:
            old_table_name = new_to_old_tables.get(new_table_name)
            if not old_table_name:
                continue
            
            for old_col, new_col in self.column_mappings[new_table_name].items():
                # Handle alias.column references
                alias_pattern = rf'\b[a-zA-Z_]\w*\.{re.escape(old_col)}\b'
                alias_replace_pattern = rf'\b([a-zA-Z_]\w*)\.{re.escape(old_col)}\b'
                corrected_content = re.sub(alias_replace_pattern, rf'\1.{new_col}', corrected_content, flags=re.IGNORECASE)
                
                # Handle standalone column references
                if re.search(rf'\bFROM\b.*\b{re.escape(old_table_name)}\b', corrected_content, re.IGNORECASE):
                    standalone_pattern = rf'\b{re.escape(old_col)}\b(?!\s*\()'
                    lines = corrected_content.split('\n')
                    for i, line in enumerate(lines):
                        if re.search(standalone_pattern, line, re.IGNORECASE):
                            if not re.search(rf'\w+\.{re.escape(old_col)}\b', line, re.IGNORECASE):
                                lines[i] = re.sub(standalone_pattern, new_col, line, flags=re.IGNORECASE)
                    corrected_content = '\n'.join(lines)
        
        return corrected_content


def main():
    st.set_page_config(
        page_title="SQL Mapping Reviewer Dashboard",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🔍 SQL Mapping Reviewer Dashboard")
    st.markdown("---")
    
    # Sidebar for file uploads
    st.sidebar.header("📁 File Upload")
    
    # Upload Excel mapping file
    st.sidebar.subheader("1. Upload Mapping File")
    mapping_file = st.sidebar.file_uploader(
        "Choose Excel mapping file",
        type=['xlsx', 'xls'],
        help="Excel file with 'TableMappings' and 'ColumnMappings' sheets",
        key="mapping_file"
    )
    
    # Upload SQL files
    st.sidebar.subheader("2. Upload SQL Files")
    sql_files = st.sidebar.file_uploader(
        "Choose SQL files",
        type=['sql'],
        accept_multiple_files=True,
        help="Select one or more SQL files to analyze",
        key="sql_files"
    )
    
    # Main content area
    if mapping_file and sql_files:
        st.info(f"📁 Mapping file: {mapping_file.name} ({mapping_file.size} bytes)")
        st.info(f"📄 SQL files: {len(sql_files)} files uploaded")
        
        # Load mapping data
        try:
            # Show progress
            with st.spinner("Loading mapping file..."):
                table_mappings_df = pd.read_excel(mapping_file, sheet_name='TableMappings')
                column_mappings_df = pd.read_excel(mapping_file, sheet_name='ColumnMappings')
            
            st.success(f"✅ Loaded mappings: {len(table_mappings_df)} table mappings, {len(column_mappings_df)} column mappings")
            
            # Show mapping preview
            with st.expander("📋 Preview Mappings"):
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Table Mappings")
                    st.dataframe(table_mappings_df)
                with col2:
                    st.subheader("Column Mappings")
                    st.dataframe(column_mappings_df)
            
        except Exception as e:
            st.error(f"❌ Error loading mapping file: {str(e)}")
            return
        
        # Initialize reviewer
        reviewer = SQLMappingReviewer()
        if not reviewer.load_mappings_from_dataframe(table_mappings_df, column_mappings_df):
            st.error("❌ Failed to process mappings")
            return
        
        # Process SQL files
        st.header("📊 Analysis Results")
        
        analysis_results = {}
        
        # Process files with progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, sql_file in enumerate(sql_files):
            status_text.text(f"Processing {sql_file.name}...")
            progress_bar.progress((i + 1) / len(sql_files))
            
            try:
                # Read SQL content
                sql_content = sql_file.read().decode('utf-8')
                sql_file.seek(0)  # Reset file pointer
                
                # Analyze SQL
                issues = reviewer.analyze_sql_content(sql_content, sql_file.name)
                
                # Apply corrections
                corrected_content = reviewer.apply_corrections(sql_content)
                
                analysis_results[sql_file.name] = {
                    'original': sql_content,
                    'issues': issues,
                    'corrected': corrected_content
                }
            except Exception as e:
                st.error(f"Error processing {sql_file.name}: {str(e)}")
                analysis_results[sql_file.name] = {
                    'original': "",
                    'issues': [f"ERROR: Failed to process file - {str(e)}"],
                    'corrected': ""
                }
        
        status_text.text("✅ Processing complete!")
        progress_bar.progress(1.0)
        
        # Display results in tabs
        tab1, tab2, tab3 = st.tabs(["🔍 Analysis Report", "📝 Original vs Corrected", "📥 Download Results"])
        
        with tab1:
            st.subheader("Analysis Report")
            
            for filename, result in analysis_results.items():
                with st.expander(f"📄 {filename}"):
                    if result['issues']:
                        st.warning(f"Found {len(result['issues'])} issues:")
                        for issue in result['issues']:
                            if issue.startswith('ERROR'):
                                st.error(f"🚨 {issue}")
                            elif issue.startswith('WARNING'):
                                st.warning(f"⚠️ {issue}")
                            elif issue.startswith('TABLE MAPPING'):
                                st.info(f"🔄 {issue}")
                            elif issue.startswith('COLUMN MAPPING'):
                                st.info(f"🔄 {issue}")
                            else:
                                st.write(f"ℹ️ {issue}")
                    else:
                        st.success("✅ No issues found!")
        
        with tab2:
            st.subheader("Original vs Corrected SQL")
            
            selected_file = st.selectbox(
                "Select file to compare:",
                list(analysis_results.keys())
            )
            
            if selected_file:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🔴 Original SQL")
                    st.code(analysis_results[selected_file]['original'], language='sql')
                
                with col2:
                    st.subheader("🟢 Corrected SQL")
                    st.code(analysis_results[selected_file]['corrected'], language='sql')
        
        with tab3:
            st.subheader("Download Results")
            
            # Create download options
            col1, col2, col3 = st.columns(3)
            
            with col1:
                # Download individual corrected files
                st.write("**📁 Individual Files**")
                for filename, result in analysis_results.items():
                    corrected_filename = f"corrected_{filename}"
                    st.download_button(
                        label=f"📥 {corrected_filename}",
                        data=result['corrected'],
                        file_name=corrected_filename,
                        mime='text/plain'
                    )
            
            with col2:
                # Download all as ZIP
                st.write("**📦 All Files (ZIP)**")
                if st.button("🗜️ Generate ZIP"):
                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for filename, result in analysis_results.items():
                            corrected_filename = f"corrected_{filename}"
                            zip_file.writestr(corrected_filename, result['corrected'])
                    
                    st.download_button(
                        label="📥 Download All Corrected Files",
                        data=zip_buffer.getvalue(),
                        file_name="corrected_sql_files.zip",
                        mime='application/zip'
                    )
            
            with col3:
                # Download analysis report
                st.write("**📊 Analysis Report**")
                
                # Create detailed report
                report_data = {
                    "analysis_summary": {
                        "total_files": len(analysis_results),
                        "files_with_issues": sum(1 for r in analysis_results.values() if r['issues'])
                    },
                    "file_details": {}
                }
                
                for filename, result in analysis_results.items():
                    report_data["file_details"][filename] = {
                        "issues_count": len(result['issues']),
                        "issues": result['issues']
                    }
                
                report_json = json.dumps(report_data, indent=2)
                
                st.download_button(
                    label="📥 Download Analysis Report (JSON)",
                    data=report_json,
                    file_name="sql_analysis_report.json",
                    mime='application/json'
                )
        
        # Summary statistics
        st.markdown("---")
        st.header("📈 Summary Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Files Processed", len(analysis_results))
        
        with col2:
            files_with_issues = sum(1 for r in analysis_results.values() if r['issues'])
            st.metric("Files with Issues", files_with_issues)
        
        with col3:
            total_issues = sum(len(r['issues']) for r in analysis_results.values())
            st.metric("Total Issues Found", total_issues)
        
        with col4:
            table_mappings_applied = sum(
                len([i for i in r['issues'] if 'TABLE MAPPING' in i]) 
                for r in analysis_results.values()
            )
            st.metric("Table Mappings Applied", table_mappings_applied)
    
    else:
        # Welcome screen
        st.markdown("""
        ## Welcome to the SQL Mapping Reviewer! 👋
        
        This dashboard helps you:
        - 🔍 **Analyze SQL files** for mapping compliance
        - 🔄 **Apply table and column mappings** automatically
        - 📊 **Generate detailed reports** of issues found
        - 📥 **Download corrected SQL files**
        
        ### How to use:
        1. **Upload your Excel mapping file** (with 'TableMappings' and 'ColumnMappings' sheets)
        2. **Upload your SQL files** that need to be reviewed
        3. **Review the analysis results** and download corrected files
        
        ### Excel File Format:
        
        **TableMappings sheet:**
        - `OldTableName`: Current table name in SQL
        - `NewTableName`: New table name to use
        - `ChangeType`: Type of change (optional)
        - `Notes`: Additional notes (optional)
        
        **ColumnMappings sheet:**
        - `TableName`: Table name (use NEW table name)
        - `OldColumnName`: Current column name
        - `NewColumnName`: New column name to use
        - `DataTypeChange`: Data type changes (optional)
        - `Notes`: Additional notes (optional)
        """)
        
        # Show sample data
        with st.expander("📋 Sample Mapping Data Format"):
            st.write("**Sample TableMappings:**")
            sample_table_df = pd.DataFrame({
                'OldTableName': ['customers', 'orders_legacy', 'prod.inventory'],
                'NewTableName': ['client', 'transactions', 'warehouse.stock'],
                'ChangeType': ['Rename', 'Rename', 'Schema Change'],
                'Notes': ['New client terminology', 'New system table', 'Moved to new schema']
            })
            st.dataframe(sample_table_df)
            
            st.write("**Sample ColumnMappings:**")
            sample_column_df = pd.DataFrame({
                'TableName': ['client', 'client', 'transactions', 'transactions'],
                'OldColumnName': ['cust_id', 'name', 'order_date', 'amount'],
                'NewColumnName': ['client_id', 'client_name', 'transaction_dt', 'total_amount'],
                'DataTypeChange': ['None', 'None', 'DATE', 'DECIMAL(10,2)'],
                'Notes': ['Standardized naming', 'More descriptive', 'New data type', 'Increased precision']
            })
            st.dataframe(sample_column_df)


if __name__ == "__main__":
    main()
