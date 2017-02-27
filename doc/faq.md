# FAQ

### Different installation methods

The OpenQuake Engine has at least three installation methods. To choose the one that best fits your needs take a look at the **[installation overview](installing/overview.md)**.

***

### Supported operating systems

Binary packages are provided for the following 64bit operating systems:
- [Windows](installing/windows.md)
- [macOS](installing/macos.md)
- Linux [Ubuntu](installing/ubuntu.md) and [RedHat/CentOS/Scientific Linux](installing/rhel.md) via _deb_ and _rpm_
- Any other generic Linux distribution via a [self-installable binary distribution](installing/linux-generic.md)
- [Docker](installing/docker.md) hosts

A 64bit operating system **is required**. Please refer to each OS specific page for details about requirements.

***

### Unsupported operating systems

Binary packages *may* work on Ubuntu derivatives and Debian if the dependencies are satisfied; these configurations are known to work:
- **Ubuntu 14.04** (Trusty) packages work on **Mint Linux 17** and on **Debian 8.0** (Jessie)
- **Ubuntu 16.04** (Xenial) packages work on **Mint Linux 18** and on **Debian unstable**
- **RHEL 7** packages generally work on **Fedora**

These configurations however are not tested by our [continuous integration system](https://ci.openquake.org) and we cannot guarantee on the quality of the results. Use at your own risk.

Another installation option for unsupported Linux systems is provided by the **[self-installable binary distribution for generic Linux](installing/linux-generic.md)**.

***

### Celery support

Starting with OpenQuake Engine 2.0 Celery isn't needed (and not recommended) on a single machine setup; the OpenQuake Engine is able to use all the available CPU cores even without Celery.
Celery must be enabled on a cluster / multi node setup. To enable it please refer to the [multiple nodes installation guidelines](installing/cluster.md).

***

### MPI support

MPI is not supported by the OpenQuake Engine. Task distribution across network interconnected nodes is made via *Celery* and *RabbitMQ* as broker. No filesystem sharing is needed between the nodes and data transfer is made on plain TCP/IP connection. For a cluster setup see the [hardware suggestions](hardware-suggestions.md) and [cluster](installing/cluster.md) pages.

MPI support may be added in the future if sponsored by someone. If you would like to help support development of OpenQuake, please contact us at [partnership@globalquakemodel.org](mailto:partnership@globalquakemodel.org).

***

### error: [Errno 111] Connection refused

A more detailed stack trace:

```Python
File "/usr/local/lib/python2.6/dist-packages/carrot/connection.py", line 135, in connection
    self._connection = self._establish_connection()
File "/usr/local/lib/python2.6/dist-packages/carrot/connection.py", line 148, in _establish_connection
    return self.create_backend().establish_connection()
File "/usr/local/lib/python2.6/dist-packages/carrot/backends/pyamqplib.py", line 208, in establish_connection
    connect_timeout=conninfo.connect_timeout)
File "/usr/local/lib/python2.6/dist-packages/amqplib/client_0_8/connection.py", line 125, in __init__
    self.transport = create_transport(host, connect_timeout, ssl)
File "/usr/local/lib/python2.6/dist-packages/amqplib/client_0_8/transport.py", line 220, in create_transport
    return TCPTransport(host, connect_timeout)
File "/usr/local/lib/python2.6/dist-packages/amqplib/client_0_8/transport.py", line 58, in __init__
    self.sock.connect((host, port))
File "", line 1, in connect
error: [Errno 111] Connection refused
```

This happens when the **Celery support is enabled but RabbitMQ server is not running**. You can start it running
```bash
$ sudo service rabbitmq-server start
``` 

***

### error: [Errno 104] Connection reset by peer

A more detailed stack trace:

```python
Traceback (most recent call last):
  File "/usr/lib/python2.7/dist-packages/celery/worker/__init__.py", line 206, in start
    self.blueprint.start(self)
  File "/usr/lib/python2.7/dist-packages/celery/bootsteps.py", line 119, in start
    self.on_start()
  File "/usr/lib/python2.7/dist-packages/celery/apps/worker.py", line 165, in on_start
    self.purge_messages()
  File "/usr/lib/python2.7/dist-packages/celery/apps/worker.py", line 189, in purge_messages
    count = self.app.control.purge()
  File "/usr/lib/python2.7/dist-packages/celery/app/control.py", line 145, in purge
    return self.app.amqp.TaskConsumer(conn).purge()
  File "/usr/lib/python2.7/dist-packages/celery/app/amqp.py", line 375, in __init__
    **kw
  File "/usr/lib/python2.7/dist-packages/kombu/messaging.py", line 364, in __init__
    self.revive(self.channel)
  File "/usr/lib/python2.7/dist-packages/kombu/messaging.py", line 369, in revive
    channel = self.channel = maybe_channel(channel)
  File "/usr/lib/python2.7/dist-packages/kombu/connection.py", line 1054, in maybe_channel
    return channel.default_channel
  File "/usr/lib/python2.7/dist-packages/kombu/connection.py", line 756, in default_channel
    self.connection
  File "/usr/lib/python2.7/dist-packages/kombu/connection.py", line 741, in connection
    self._connection = self._establish_connection()
  File "/usr/lib/python2.7/dist-packages/kombu/connection.py", line 696, in _establish_connection
    conn = self.transport.establish_connection()
  File "/usr/lib/python2.7/dist-packages/kombu/transport/pyamqp.py", line 116, in establish_connection
    conn = self.Connection(**opts)
  File "/usr/lib/python2.7/dist-packages/amqp/connection.py", line 180, in __init__
    (10, 30),  # tune
  File "/usr/lib/python2.7/dist-packages/amqp/abstract_channel.py", line 67, in wait
    self.channel_id, allowed_methods, timeout)
  File "/usr/lib/python2.7/dist-packages/amqp/connection.py", line 241, in _wait_method
    channel, method_sig, args, content = read_timeout(timeout)
  File "/usr/lib/python2.7/dist-packages/amqp/connection.py", line 330, in read_timeout
    return self.method_reader.read_method()
  File "/usr/lib/python2.7/dist-packages/amqp/method_framing.py", line 189, in read_method
    raise m
error: [Errno 104] Connection reset by peer
```

This means that RabbiMQ _user_ and _vhost_ have not been created or set correctly. Please refer to [cluster documentation](installing/cluster.md#rabbitmq) to fix it.

***

## Getting help
If you need help or have questions/comments/feedback for us, you can:
  * Subscribe to the OpenQuake users mailing list: https://groups.google.com/forum/?fromgroups#!forum/openquake-users
  * Contact us on IRC: irc.freenode.net, channel #openquake
