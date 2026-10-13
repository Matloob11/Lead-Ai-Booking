#!/bin/bash
for i in 1 2 3 4 5 6 7 8; do
  echo "RUN $i"
  php /tmp/_delete_empty_dupes.php
  echo "EXIT $?"
done
echo ALL_DONE
