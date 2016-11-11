#!/bin/bash
sleep_time=1
[ -z "$1" ] || sleep_time="$1"

while [ 1 ] ; do
  echo -n "sleeping time: "
  date
  sleep "$sleep_time"
done
