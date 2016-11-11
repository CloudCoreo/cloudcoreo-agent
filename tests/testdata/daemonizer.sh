#!/bin/sh

(
    echo "going to daemonize"
    nohup ./sleeper.sh 5 &
    echo "daemonized"
)
