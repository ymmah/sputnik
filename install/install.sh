#!/bin/sh

THIS=`readlink -e $0`
LOGFILE=`echo $THIS | sed 's/\.sh$/.log/'`

log()
{
    if [ X"$1" = X"-n" ]
    then
        shift
        echo -n "$@" | tee -a $LOGFILE
    else
        echo "$@" | tee -a $LOGFILE
    fi
}

error()
{
    if [ X"$1" = X"-n" ]
    then
        shift
        echo -n "$@" | tee -a $LOGFILE 1>&2
    else
        echo "$@" | tee -a $LOGFILE 1>&2
    fi
}

check_superuser()
{
    log -n "Checking for root permissions... "
    if [ `id -u` -ne 0 ]
    then
        log "failed."
        error "This script must be run as root."
        exit 1
    else
        log "ok."
    fi
}

run_script()
{
    $1 >> $LOGFILE 2>&1
}

run_scripts()
{
    if [ -d $1 ]
    then
        log "Running $1 scripts..."
        for i in $1
        do
            SCRIPT_NAME=`log $i | sed 's/.*\/[0-9-]*\(.*\)/\1/'`
            log -n "Running $SCRIPT_NAME... "
            if run_script $i
            then
                log done.
            else
                log failed.
                error "Error: could not complete $SCRIPT_NAME."
                exit 1
            fi
        done
    fi
}

check_user()
{
    log -n "Checking/adding user $1... "
    if [ `cat /etc/passwd | grep ^$1:` ]
    then
        PASSWD=`cat /etc/passwd | grep ^$1: | cut -d: -f 6,7`
        if [ X$PASSWD = X"/srv/$1:/bin/false" ]
        then
            log ok.
        else
            log failed.
            error "User $1 exists but with incorrect home or shell."
            exit 1
        fi
    else
        if /usr/sbin/adduser --quiet --system --group --home=/srv/$1 $1 >> $LOGFILE 2>&1
        then
            log "ok."
        else
            log "failed."
            error "Error: cannot create user $1."
            exit 1
        fi
    fi
}

check_dpkg_dependency()
{
    /usr/bin/dpkg -s $1 >> $LOGFILE 2>&1
}

install_dpkg_dependency()
{
    DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get -y install $1 >> $LOGFILE 2>&1
}

check_source_dependency()
{
    $1 check >> $LOGFILE 2>&1
}

install_source_dependency()
{
    $1 install >> $LOGFILE 2>&1
}

check_python_dependency()
{
    /usr/bin/pip freeze 2>>$LOGFILE | grep $1 >> $LOGFILE 2>&1
}

install_python_dependency()
{
    /usr/bin/pip install $1 >> $LOGFILE 2>&1
}

check_dependencies()
{
    cd deps
    log "Checking $1 dependencies..."
    DEPENDENCY_FILE=${1}-dependencies
    if [ -d $DEPENDENCY_FILE ]
    then
        DIR=1
        DEPENDENCIES=`ls $DEPENDENCY_FILE/*`
    else
        DEPENDENCIES=`cat $DEPENDENCY_FILE`
    fi
    for i in $DEPENDENCIES
    do
        if [ ! -z $DIR ]
        then
            PACKAGE_NAME=`log $i | sed 's/.*\/[0-9-]*\(.*\)/\1/'`
        else
            PACKAGE_NAME=$i
        fi
        if check_${1}_dependency $i
        then
            log $PACKAGE_NAME installed.
        else
            log -n "$PACKAGE_NAME not installed. Installing... "
            install_${1}_dependency $i
            if check_${1}_dependency $i
            then
                log done.
            else
                log failed.
                error "Error: unable to install $PACKAGE_NAME."
                exit 1
            fi
        fi
    done
    cd ..
}

install()
{
    mkdir -p /srv/sputnik
    cp -Rp server /srv/sputnik
    cp -Rp www /srv/sputnik
}

: > $LOGFILE

check_superuser

run_scripts pre-install

check_user sputnik
check_user bitcoind

check_dependencies dpkg
check_dependencies source
check_dependencies python

install

run_scripts post-install

