### Fixed

- GUI-hog load-source labels never carry command-line text: a process is named from the kernel's executable path, asked for every process (the first word `ps` prints can be argv[1] or an environment string when argv[0] is empty, and an argv[0] with a space is cut inside its path), and `?` when that path is unreadable because the process exited; the earlier "never from argv" wording in the docs and changelog is corrected. (#875)
