#!/bin/bash

# Build script for Bitcoin Node Manager
# This script compiles the Python app into a macOS .app bundle

echo "=================================================="
echo "Bitcoin Node Manager - Build Script"
echo "=================================================="
echo ""

# Check if pyinstaller is installed
if ! command -v pyinstaller &> /dev/null
then
    echo "PyInstaller not found. Installing..."
    pip3 install pyinstaller
fi

# Check if requests is installed
echo "Checking dependencies..."
pip3 install -r requirements.txt

echo ""
echo "Building application..."
echo ""

# Build using the spec file (recommended)
if [ -f "BitcoinNodeManager.spec" ]; then
    echo "Using BitcoinNodeManager.spec file..."
    pyinstaller BitcoinNodeManager.spec
else
    # Build with command-line options
    echo "Building with default options..."
    pyinstaller --name="BitcoinNodeManager" \
                --windowed \
                --onefile \
                bitcoin_node_manager.py
fi

# Check if build was successful
if [ -d "dist/BitcoinNodeManager.app" ]; then
    echo ""
    echo "=================================================="
    echo "Build successful!"
    echo "=================================================="
    echo ""
    echo "Your application is located at:"
    echo "  dist/BitcoinNodeManager.app"
    echo ""
    echo "To use it:"
    echo "  1. Copy BitcoinNodeManager.app to your SSD root folder"
    echo "  2. Ensure Binaries/, BitcoinChain/, and ElectrsDB/ folders exist"
    echo "  3. Double-click the app or run: open BitcoinNodeManager.app"
    echo ""
else
    echo ""
    echo "=================================================="
    echo "Build failed!"
    echo "=================================================="
    echo ""
    echo "Please check the error messages above."
    exit 1
fi

# Optional: Clean up build files
read -p "Clean up build files (build/ folder)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleaning up..."
    rm -rf build/
    echo "Done!"
fi

echo ""
echo "Build process complete!"
