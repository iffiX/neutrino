cmake_minimum_required(VERSION 3.22.1)
project(neutrino_rustdesk C)

add_library(neutrino_rustdesk SHARED rustdesk_jni.c)
target_link_libraries(neutrino_rustdesk android dl)
target_link_options(neutrino_rustdesk PRIVATE "-Wl,-z,max-page-size=16384")
