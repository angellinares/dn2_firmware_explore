/* The firmware addresses for the OS a build targets (issue #382).
 *
 * A source that includes this file builds for either OS from one text: the build
 * defines DN2_OS_112 for Digitone II OS 1.12 (dn2_112.h, generated from dn2_111.h
 * through the address map) and nothing for 1.11 (dn2_111.h). A source moves from
 * dn2_111.h to this file when its mod is ported; until then it stays 1.11 only.
 */
#ifndef DN2_H
#define DN2_H

#if defined(DN2_OS_112)
#include "dn2_112.h"
#else
#include "dn2_111.h"
#endif

#endif
