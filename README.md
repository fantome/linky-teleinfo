# Linky-teleinfo

Collect electricity teleinfo from linky base on serial connection.
And send data to a remote InfluxDB.

## Deploy

Edit `deploy/hosts` file to set your host.

Create config file `/etc/linky-teleinfo.conf` on target host.
```ini
[influxdb]
host=domain.tld
path=influxdb
username=user
password=pass
db=teleinfo

[tags]
host=home
region=linky
```

And run ansible
```bash
ansible-playbook -i deploy/hosts deploy/playbooks/main.yml
```