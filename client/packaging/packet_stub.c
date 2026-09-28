/*
 * packet.dll: a stand-in for the Packet.dll of Npcap, carried beside
 * easytier-core.exe in the Windows client.
 *
 * easytier-core imports these eleven functions from Packet.dll through the
 * pnet crate, and Windows refuses to start it without a Packet.dll to load.
 * The client never opens a capture adapter, so every function answers
 * failure or nothing. Npcap itself is neither carried nor needed.
 *
 * Built with MSVC: cl /nologo /O2 /LD packet_stub.c /Fe:packet.dll
 */
#include <windows.h>

__declspec(dllexport) BOOLEAN PacketGetAdapterNames(char *buffer, ULONG *length)
{
    if (length) {
        *length = 0;
    }
    return FALSE;
}

__declspec(dllexport) void *PacketOpenAdapter(char *name)
{
    return NULL;
}

__declspec(dllexport) void PacketCloseAdapter(void *adapter)
{
}

__declspec(dllexport) BOOLEAN PacketSendPacket(void *adapter, void *packet, BOOLEAN sync)
{
    return FALSE;
}

__declspec(dllexport) BOOLEAN PacketSetBuff(void *adapter, int size)
{
    return FALSE;
}

__declspec(dllexport) BOOLEAN PacketSetMinToCopy(void *adapter, int bytes)
{
    return FALSE;
}

__declspec(dllexport) BOOLEAN PacketReceivePacket(void *adapter, void *packet, BOOLEAN sync)
{
    return FALSE;
}

__declspec(dllexport) BOOLEAN PacketSetHwFilter(void *adapter, ULONG filter)
{
    return FALSE;
}

__declspec(dllexport) void *PacketAllocatePacket(void)
{
    return NULL;
}

__declspec(dllexport) void PacketFreePacket(void *packet)
{
}

__declspec(dllexport) void PacketInitPacket(void *packet, void *buffer, UINT length)
{
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    return TRUE;
}
