# getpocket-subscriber
usage:
  - install reqs: pip install -r requirements.txt
  - modify config.cfg: 
    - sqlite_path - path to the sqlite db file that will store status info.
    - opml_path - path to the OPML file to read.
    - pocket_consumer_key - a key getpocket api needs to authenticate user.
    - pocket_access_token - a token for getpocket api.
  - run: python subcriber.py --config-file config.cfg
  
