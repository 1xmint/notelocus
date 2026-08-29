"""notelocus — converge scattered notes into the ideas they are about.

`locus`, in mathematics, is the set of points satisfying a condition. A note on
a desktop is rarely one idea; it is a conversation, a paste, a jotted line. This
finds the ideas and gives each one a stable address.

`tidy` files loose desktop notes into topic folders. It moves them and nothing
else: it never deletes and never overwrites, every run records what it did, and
`undo` reads that back.

`index` and `find` only read, and never write outside the folder they are given.
"""

__version__ = "0.2.0"
