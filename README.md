# getpocket-subscriber
usage:
  - install reqs: pip install -r requirements.txt
  - modify config.cfg: 
    - sqlite_path - path to the sqlite db file that will store its info.
    - opml_path - path to the OPML file to read.
    - pocket_consumer_key - A key getpocket api needs to authenticate user.
    - pocket_access_token - A token for getpocket api.
  - run: python subcriber.py --config-file config.cfg
  
