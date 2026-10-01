// The JNI side of RustDeskNative: opens librustdesk.so, which System.loadLibrary has already
// loaded, and forwards each call to the C interface packaging/build/build_core_rustdesk.patch adds.

#include <android/native_window_jni.h>
#include <dlfcn.h>
#include <jni.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    void *context;
    void (*on_state)(void *context, int state, const char *text);
    void (*on_size)(void *context, int width, int height);
} NdCallbacks;

static void (*nd_init)(const char *app_dir);
static int (*nd_start)(const char *peer, int port, const char *password, NdCallbacks callbacks);
static void (*nd_attach_window)(ANativeWindow *window);
static void (*nd_mouse)(int x, int y, int mask);
static void (*nd_key)(const char *name, bool down);
static void (*nd_text)(const char *text);
static void (*nd_close)(void);

static JavaVM *java_vm;
static pthread_key_t attached_key;
static jobject listener;
static jmethodID on_state_method;
static jmethodID on_size_method;

static void detach_thread(void *env) {
    (void) env;
    (*java_vm)->DetachCurrentThread(java_vm);
}

static JNIEnv *thread_env(void) {
    JNIEnv *env = NULL;
    if ((*java_vm)->GetEnv(java_vm, (void **) &env, JNI_VERSION_1_6) == JNI_OK) return env;
    if ((*java_vm)->AttachCurrentThread(java_vm, &env, NULL) != JNI_OK) return NULL;
    pthread_setspecific(attached_key, env);
    return env;
}

static void forward_state(void *context, int state, const char *text) {
    JNIEnv *env = thread_env();
    if (env == NULL) return;
    jstring words = (*env)->NewStringUTF(env, text);
    (*env)->CallVoidMethod(env, (jobject) context, on_state_method, state, words);
    (*env)->DeleteLocalRef(env, words);
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}

static void forward_size(void *context, int width, int height) {
    JNIEnv *env = thread_env();
    if (env == NULL) return;
    (*env)->CallVoidMethod(env, (jobject) context, on_size_method, width, height);
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}

JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void) reserved;
    java_vm = vm;
    pthread_key_create(&attached_key, detach_thread);
    return JNI_VERSION_1_6;
}

JNIEXPORT jboolean JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_open(JNIEnv *env, jobject self) {
    (void) env;
    (void) self;
    void *core = dlopen("librustdesk.so", RTLD_NOW | RTLD_NOLOAD);
    if (core == NULL) return JNI_FALSE;
    nd_init = dlsym(core, "nd_init");
    nd_start = dlsym(core, "nd_start");
    nd_attach_window = dlsym(core, "nd_attach_window");
    nd_mouse = dlsym(core, "nd_mouse");
    nd_key = dlsym(core, "nd_key");
    nd_text = dlsym(core, "nd_text");
    nd_close = dlsym(core, "nd_close");
    bool is_complete = nd_init && nd_start && nd_attach_window && nd_mouse && nd_key && nd_text
                       && nd_close;
    return is_complete ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_init(JNIEnv *env, jobject self,
                                                                 jstring app_dir) {
    (void) self;
    const char *path = (*env)->GetStringUTFChars(env, app_dir, NULL);
    nd_init(path);
    (*env)->ReleaseStringUTFChars(env, app_dir, path);
}

JNIEXPORT jint JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_start(JNIEnv *env, jobject self,
                                                                  jstring peer, jint port,
                                                                  jstring password,
                                                                  jobject events) {
    (void) self;
    jclass kind = (*env)->GetObjectClass(env, events);
    on_state_method = (*env)->GetMethodID(env, kind, "onState", "(ILjava/lang/String;)V");
    on_size_method = (*env)->GetMethodID(env, kind, "onSize", "(II)V");
    listener = (*env)->NewGlobalRef(env, events);
    NdCallbacks callbacks = {listener, forward_state, forward_size};
    const char *host = (*env)->GetStringUTFChars(env, peer, NULL);
    const char *secret = (*env)->GetStringUTFChars(env, password, NULL);
    int result = nd_start(host, port, secret, callbacks);
    (*env)->ReleaseStringUTFChars(env, password, secret);
    (*env)->ReleaseStringUTFChars(env, peer, host);
    if (result != 0) {
        (*env)->DeleteGlobalRef(env, listener);
        listener = NULL;
    }
    return result;
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_attach(JNIEnv *env, jobject self,
                                                                   jobject surface) {
    (void) self;
    ANativeWindow *window = surface == NULL ? NULL : ANativeWindow_fromSurface(env, surface);
    nd_attach_window(window);
    if (window != NULL) ANativeWindow_release(window);
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_mouse(JNIEnv *env, jobject self,
                                                                  jint x, jint y, jint mask) {
    (void) env;
    (void) self;
    nd_mouse(x, y, mask);
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_key(JNIEnv *env, jobject self,
                                                                jstring name, jboolean down) {
    (void) self;
    const char *key = (*env)->GetStringUTFChars(env, name, NULL);
    nd_key(key, down == JNI_TRUE);
    (*env)->ReleaseStringUTFChars(env, name, key);
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_text(JNIEnv *env, jobject self,
                                                                 jbyteArray utf8) {
    (void) self;
    jsize length = (*env)->GetArrayLength(env, utf8);
    char *typed = calloc((size_t) length + 1, 1);
    if (typed == NULL) return;
    (*env)->GetByteArrayRegion(env, utf8, 0, length, (jbyte *) typed);
    nd_text(typed);
    free(typed);
}

JNIEXPORT void JNICALL
Java_io_github_iffix_neutrino_remotedesktop_RustDeskNative_close(JNIEnv *env, jobject self) {
    (void) self;
    nd_close();
    if (listener != NULL) {
        (*env)->DeleteGlobalRef(env, listener);
        listener = NULL;
    }
}
