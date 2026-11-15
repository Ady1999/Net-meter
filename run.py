"""Start NetMeter.  Use --startup when launched at sign-in (adds a short delay)."""
import sys

from netmeter.app import main

if __name__ == "__main__":
    main(sys.argv[1:])
