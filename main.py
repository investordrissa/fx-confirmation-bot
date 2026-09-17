from scanner import ForexScanner

if __name__ == "__main__":
    print("Forex Scanner v3 (GitHub Actions) - single pass starting.")
    scanner = ForexScanner()
    scanner.scan_all()
    print("Scan complete.")
