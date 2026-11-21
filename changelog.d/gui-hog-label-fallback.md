### Fixed

- GUI-hog load-source labels: when the kernel executable path is not readable (the process exited between the table read and the lookup), a label is the base name of argv[0] alone, so a later argument that holds `/Contents/MacOS/` (`tool SECRET/Contents/MacOS/hunter2`) never reaches it; the earlier changelog and docs wording "never from argv" now says "when readable". (#875)
