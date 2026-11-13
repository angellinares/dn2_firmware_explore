/* LFO4's own stock addresses for the OS a build targets (issue #382): stock_112.h when the
 * build defines DN2_OS_112, stock_111.h otherwise. As csrc/include/dn2.h. */
#ifndef LFO4_STOCK_H
#define LFO4_STOCK_H

#if defined(DN2_OS_112)
#include "stock_112.h"
#else
#include "stock_111.h"
#endif

#endif
