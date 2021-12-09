import sys
from arutz_meir_grabber import grab as grab_meir
from arutz_meir_grabber import grab_widgets as grab_meir_widgets
from bnei_david_grabber import grab, grab_main_page
from postgres_to_sql_converter import start_conversion
from youtube_grabber import grab_yotube
import json
import os

from sql_helper import get_timestamp

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print('grabbing main page')
        grab_main_page()
        grab_yotube()
        # grab_meir_widgets()
    else:
        print('grabbing all')
        now = get_timestamp()
        grab()
        grab_meir()
        root_path = "%s/.." % os.path.dirname(os.path.realpath(__file__))
        with open('{}/general.json'.format(root_path), 'r+') as f:
            data = json.load(f)
            data['last_run'] = now
            f.seek(0)  # <--- should reset file position to the beginning.
            json.dump(data, f, indent=4)
            f.truncate()
    start_conversion()
