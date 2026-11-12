| The stock addresses for the OS being built (issue #382): dn2_112.inc when DN2_OS_112 is
| defined (gen_usbprobe_code.py --os 1.12), else dn2_111.inc.
#ifdef DN2_OS_112
#include "dn2_112.inc"
#else
#include "dn2_111.inc"
#endif
