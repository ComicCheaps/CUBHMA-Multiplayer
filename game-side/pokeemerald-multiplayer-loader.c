/*
 * CUBHMA local multiplayer payload bootstrap for pret/pokeemerald.
 * The generated ROM remains based on the user's clean English Emerald v1.0.
 */
#include "global.h"

#define CUBHMA_PAYLOAD_EWRAM_BASE  0x0203CF80u
#define CUBHMA_PAYLOAD_MAX_CLEAR   0x00002E80u
#define CUBHMA_GAMEPAK_ROM_BASE    0x08000000u
#define CUBHMA_GAMEPAK_ROM_END     0x0A000000u
#define CUBHMA_IRQ_VECTOR          ((volatile u32 *)0x03007FFCu)
#define CUBHMA_PAYLOAD_MAGIC       0x4B4F4F48u /* "HOOK" in little endian */

/*
 * Replaced by tools/package_multiplayer_payload.py:
 * [0] appended payload ROM address, [1] payload byte size,
 * [2] payload_end - PAYLOAD_BASE (the EWRAM region to clear).
 */
const u32 gCubhmaMultiplayerPayloadDescriptor[3] = {
    0xC0B4A001u,
    0xC0B4A002u,
    0xC0B4A003u,
};

void CUBHMAMultiplayerPayloadInit(void)
{
    const volatile u32 *descriptor = gCubhmaMultiplayerPayloadDescriptor;
    u32 romAddress = descriptor[0];
    u32 payloadSize = descriptor[1];
    u32 clearSize = descriptor[2];
    volatile u8 *destination = (volatile u8 *)CUBHMA_PAYLOAD_EWRAM_BASE;
    const volatile u8 *source;
    volatile u32 *payloadHeader;
    u32 oldIrqVector;
    u32 i;

    /* Unpackaged builds retain the marker words and do nothing. */
    if (romAddress < CUBHMA_GAMEPAK_ROM_BASE || romAddress >= CUBHMA_GAMEPAK_ROM_END)
        return;
    if (payloadSize < 12u || payloadSize > CUBHMA_PAYLOAD_MAX_CLEAR)
        return;
    if (romAddress + payloadSize < romAddress || romAddress + payloadSize > CUBHMA_GAMEPAK_ROM_END)
        return;
    if (clearSize < payloadSize || clearSize > CUBHMA_PAYLOAD_MAX_CLEAR)
        return;

    oldIrqVector = *CUBHMA_IRQ_VECTOR;
    for (i = 0; i < clearSize; i++)
        destination[i] = 0;

    source = (const volatile u8 *)romAddress;
    for (i = 0; i < payloadSize; i++)
        destination[i] = source[i];

    /* Payload header: branch at +0, original IRQ target at +4, magic at +8. */
    payloadHeader = (volatile u32 *)CUBHMA_PAYLOAD_EWRAM_BASE;
    if (payloadHeader[2] != CUBHMA_PAYLOAD_MAGIC)
        return;

    payloadHeader[1] = oldIrqVector;

    /*
     * Leave the live IRQ vector alone at boot. The mGBA client script detects
     * whether it has injected the payload by checking that vector; if it were
     * already pointing into this payload, the script would skip startup and
     * never establish the local network bridge. The script will overwrite
     * this reserved EWRAM region and install the hook after entering the
     * overworld.
     */
}
