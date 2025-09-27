#!/usr/bin/env python3
"""
Simple launcher for SQL Mapping Reviewer Dashboard
"""

import subprocess
import sys
import webbrowser
import time
import os

def check_requirements():
    """Check if required packages are installed"""
    required_packages = ['streamlit', 'pandas', 'sqlparse', 'openpyxl']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n💡 Install them with:")
        print("   pip install -r requirements.txt")
        return False
    
    return True

def launch_dashboard():
    """Launch the Streamlit dashboard"""
    print("🚀 Starting SQL Mapping Reviewer Dashboard...")
    print("📋 Checking requirements...")
    
    if not check_requirements():
        return
    
    print("✅ All requirements satisfied!")
    print("🌐 Starting dashboard server...")
    
    try:
        # Start Streamlit
        process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", 
            "sql_mapping_dashboard.py",
            "--server.port", "8501",
            "--server.address", "localhost"
        ])
        
        print("⏳ Waiting for server to start...")
        time.sleep(3)
        
        # Open browser
        url = "http://localhost:8501"
        print(f"🌍 Opening browser at {url}")
        webbrowser.open(url)
        
        print("\n" + "="*50)
        print("🎉 Dashboard is now running!")
        print("📍 URL: http://localhost:8501")
        print("🛑 Press Ctrl+C to stop the server")
        print("="*50)
        
        # Wait for the process
        process.wait()
        
    except KeyboardInterrupt:
        print("\n🛑 Stopping dashboard...")
        process.terminate()
    except Exception as e:
        print(f"❌ Error starting dashboard: {e}")

if __name__ == "__main__":
    launch_dashboard()
