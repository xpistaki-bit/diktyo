import os
import sys
import tempfile

# Eigenes Datenverzeichnis, bevor die App importiert wird
os.environ["DIKTYO_DATA"] = tempfile.mkdtemp(prefix="diktyo-test-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
