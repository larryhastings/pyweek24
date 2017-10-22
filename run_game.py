import sys

if sys.version_info < (3, 6):
    sys.exit(
        "This game requires Python 3.6 or later."
    )

import os
from pathlib import Path


dist = Path(__file__).parent.resolve()

src = str(dist / 'src')
sys.path.insert(0, src)
os.chdir(src)


try:
    import main
except ImportError:
    import traceback
    traceback.print_exc()

    req = dist / 'requirements.txt'
    sys.exit(
        """
Please ensure you have the following packages installed:

%s
You can run 'pip install -r requirements.txt' to install these (currently this
will require a compiler to be configured).

You will also require AVBin from
https://avbin.github.io/AVbin/Download.html
""" % req.read_text()
    )
