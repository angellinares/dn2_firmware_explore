/* One track's audio, as the DN2's SHARC sent it to the ColdFire in the last frame.
 *
 * One subject: reading a track's samples out of the two links (dn2_111.h). Any mod that
 * wants a track's sound (a scope, a meter, a follower) can take it from here.
 */
#ifndef DN2_AUDIO_TAP_H
#define DN2_AUDIO_TAP_H

#include "../include/dn2_111.h"

/* track 0..15 -> its last DN2_BLOCK samples, mono (L + R) / 2, as int16 (the top 16 of the
 * 24 bits); returns 0 for a track out of range */
int dn2_track_block(unsigned track, short *out);

#endif
