/* One track's audio, as the DN2's SHARC sent it to the ColdFire in the last frame.
 *
 * One subject: reading a track's samples out of the two links (dn2_111.h). Any mod that
 * wants a track's sound (a scope, a meter, a follower) can take it from here.
 */
#ifndef DN2_AUDIO_TAP_H
#define DN2_AUDIO_TAP_H

#include "../include/dn2_111.h"

/* track 0..15 -> its samples since the last call, mono (L + R) / 2, as int16 (the top 16
 * of the 24 bits), into out (room for DN2_SSI_FRAMES); returns how many: DN2_BLOCK for
 * tracks 7..16 (the reply holds one block), the frames the receive DMA wrote since the last
 * call for tracks 1..6 (about DN2_BLOCK a frame; a new track starts DN2_BLOCK back); 0 for
 * a track out of range. One caller: it keeps the SSI0 read position. */
int dn2_track_take(unsigned track, short *out);

#endif
