"""Helper modules of WSPR Logger (wspr_logger.py is the entry point that wires them together):

  db         live database: one record per heard transmission, MUF readings
  replay_db  replay database: reporter snapshots and the solar log
  analysis   propagation analysis computed from the replay database
  greyline   grey-line (twilight) test for the Analysis page
  outlook    DX outlook model and its back-test
  sun        solar elevation and sunrise / sunset
  wprs       drive detector, trips and track building for the WPRS page
  guides     lists the PDF documents in doc/
  changelog  reads CHANGELOG.md for the What's new window
"""
