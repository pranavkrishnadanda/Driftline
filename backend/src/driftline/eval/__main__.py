"""`python -m driftline.eval curate ...`: golden-set curation (see driftline.eval.curate)."""

import sys

from driftline.eval.curate import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
