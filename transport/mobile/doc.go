// Package mobile is the transport's surface for the Android and iOS apps,
// bound by gomobile: Start runs the client's local channel on a Unix socket
// in the directory the app gives, and Stop ends it. The app then speaks the
// client's local channel on that socket as the desktop client does.
package mobile
