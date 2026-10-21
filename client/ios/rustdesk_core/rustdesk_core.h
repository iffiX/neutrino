// The C interface packaging/build/build_core_rustdesk.patch adds to RustDesk, as the iOS app calls
// it. Only a device build links the library, and only code under NEUTRINO_RUSTDESK calls it.
#ifndef RUSTDESK_CORE_H
#define RUSTDESK_CORE_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    void *context;
    void (*on_state)(void *context, int state, const char *text);
    void (*on_size)(void *context, int width, int height);
    void (*on_clipboard)(void *context, const char *text);
} NdCallbacks;

void nd_init(const char *app_dir);
void nd_set_option(const char *name, const char *value);
int nd_start(const char *peer, int port, const char *password, NdCallbacks callbacks);
void nd_attach_frames(void *context,
                      void (*on_frame)(void *context, const uint8_t *bgra, int width, int height, int stride));
void nd_set_log(void *context, void (*on_log)(void *context, int level, const char *text));
void nd_mouse(int x, int y, int mask);
void nd_key(const char *name, bool down);
void nd_text(const char *text);
void nd_clipboard(const char *text);
void nd_close(void);

#endif
