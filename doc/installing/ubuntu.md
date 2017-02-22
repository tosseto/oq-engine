# Installing the OpenQuake Engine on Ubuntu Linux

The OpenQuake Engine stable tree is available in the form of *deb* binary packages for the following Ubuntu releases:
- **Ubuntu 16.04** LTS (Xenial)
- **Ubuntu 14.04** LTS (Trusty) 
- **Ubuntu 12.04** LTS (Precise)

Packages *may* work on Ubuntu derivatives (i.e. Mint Linux) and Debian, but this setup in not supported by GEM. See the **[FAQ](../faq.md#unsupported-operating-systems)**.

The software and its libraries will be installed under `/opt/openquake`. Data will be stored under `/var/lib/openquake`.

## Install packages from the OpenQuake repository

If you want to upgrade an existing installation see **[upgrading](../upgrading/ubuntu.md)**.

The following commands add the **official stable builds** package repository:
```
sudo add-apt-repository -y ppa:openquake/ppa
sudo apt-get update
```

If you want to install a **nightly build** please read the guide about installing the **[nightly build packages on Ubuntu](ubuntu-nightly.md)**.

Then to install the OpenQuake Engine and its libraries run
```bash
sudo apt-get install python-oq-engine
```

### Upgrade from a previous release

As soon as a new version of the OpenQuake Engine and libraries are released you can upgrade it using `apt` or a graphical package manager:

```bash
sudo apt update
sudo apt install python-oq-engine
```

If a full upgrade is performed on the system, the OpenQuake software is upgraded to the latest version too:

```bash
sudo apt update
sudo apt upgrade
```

## Configure the system services

The package installs three system service managed through [supervisord](http://supervisord.org/):
- `openquake-dbserver`: provides the database for the OpenQuake Engine and must be started before running any `oq engine` command
- `openquake-webui`: provides the WebUI and is optional
- `openquake-celery`: used only on a multi-node setup, not used in a default setup

`openquake-dbserver` and `openquake-webui` are started by default at boot.

To manually start, stop or restart a service run
```bash
sudo supervisorctl <start|stop|restart> openquake-dbserver openquake-webui
```

To check the status of a service run
```bash
sudo supervisorctl status openquake-dbserver openquake-webui
```

## Run the OpenQuake Engine

Continue on [How to run the OpenQuake Engine](../running/unix.md)


## Test the installation

To run the OpenQuake Engine tests see the **[testing](../testing.md)** page.


## Uninstall the OpenQuake Engine

To uninstall the OpenQuake Engine and all its components run
```bash
sudo apt-get remove python-oq-*
```
If you want to remove all the dependencies installed by the OpenQuake Engine you may then use the apt `autoremove` function and run

```bash
sudo apt-get autoremove
```

***

## Getting help
If you need help or have questions/comments/feedback for us, you can:
  * Subscribe to the OpenQuake users mailing list: https://groups.google.com/forum/?fromgroups#!forum/openquake-users
  * Contact us on IRC: irc.freenode.net, channel #openquake
