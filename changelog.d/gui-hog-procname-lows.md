### Fixed

- GUI-hog load-source labels: a name that cleans to nothing (a file name of only control characters) is now `?`, never an empty label, on every path; the docs, docstrings and the #880 entry no longer claim another user's process gets a kernel short name (`proc_name` is a same-user lookup, so it stays `?` when its path is withheld too), and a note records that a pid reused between the table read and the name lookup is display only. (#885)
