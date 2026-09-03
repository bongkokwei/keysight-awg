from m8195a import M8195A

with M8195A(host="WINDOWS-QNNRGV2") as awg:
    awg.abort()
    awg.set_output(1, False)  # pulls the output amp off
