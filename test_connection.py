"""
Quick connection test for the Keysight M8195A AWG.
Usage: python test_connection.py [resource_string]
Default resource: TCPIP0::localhost::hislip0::INSTR
"""

import sys
from m8195a import M8195A

RESOURCE = sys.argv[1] if len(sys.argv) > 1 else "TCPIP0::localhost::hislip0::INSTR"

print(f"Connecting to: {RESOURCE}")

try:
    with M8195A(RESOURCE, timeout=5_000) as awg:
        print(f"  IDN       : {awg.idn}")
        print(f"  HW Rev    : {awg.hw_revision}")
        print(f"  SCPI Ver  : {awg.system_version}")
        print(f"  Options   : {awg.options}")

        errors = awg.check_errors()
        if errors:
            print(f"  Errors    : {errors}")
        else:
            print("  Error queue: clear")

        print("\nConnection OK.")

except Exception as e:
    print(f"\nConnection FAILED: {e}")
    sys.exit(1)
