# Minitwit on Kubernetes with Persistent Volume

Minitwit based on [this source](https://github.com/kostis-codefresh/dynamic-pipelines/tree/master/my-python-app/minitwit), but extended to make use of a separate MySQL deployment with an associated persistent volume.

## Install

Create the MySQL database for the application:

```bash
kubectl create namespace minitwit
kubectl -n minitwit apply -f mysql.yaml
```

Verify `persistentvolumeclaim/mysql-pv-claim` is in a bound state:

```text
$ kubectl -n minitwit get all,pvc
NAME                         READY   STATUS    RESTARTS   AGE
pod/mysql-57899cbccb-6hx6d   1/1     Running   0          51s

NAME            TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)    AGE
service/mysql   ClusterIP   None         <none>        3306/TCP   51s

NAME                    READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/mysql   1/1     1            1           51s

NAME                               DESIRED   CURRENT   READY   AGE
replicaset.apps/mysql-57899cbccb   1         1         1       51s

NAME                                   STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS              AGE
persistentvolumeclaim/mysql-pv-claim   Bound    pvc-308c1729-63b9-46b4-96a9-c680b90d1858   100Gi      RWO            netapp-cvs-perf-premium   52s
```

Run the following command to [access the MySQL instance](https://kubernetes.io/docs/tasks/run-application/run-single-instance-stateful-application/#accessing-the-mysql-instance):

```bash
kubectl -n minitwit run -it --rm --image=mysql:8.0.34 --restart=Never mysql-client -- mysql --host mysql \
    --password=`yq '.data.db_root_password | select( . != null )' mysql.yaml | base64 --decode`
```

Once the `mysql>` command prompt is presented (you may have to hit enter), paste in the following commands:

```sql
CREATE DATABASE minitwit;
USE minitwit;

drop table if exists user;
create table user (
  user_id INT primary key auto_increment,
  username text not null,
  email text not null,
  pw_hash text not null
);

drop table if exists follower;
create table follower (
  who_id integer,
  whom_id integer
);

drop table if exists message;
create table message (
  message_id integer primary key auto_increment,
  author_id integer not null,
  text text not null,
  pub_date integer
);
```

Verify the commands ran as expected, and exit out of the container.

Create the frontend of the minitwit application with the following command:

```bash
kubectl -n minitwit apply -f minitwit.yaml
```

Verify the `service/minitwit` has an external IP:

```text
$ kubectl -n minitwit get svc    
NAME       TYPE           CLUSTER-IP      EXTERNAL-IP      PORT(S)        AGE
minitwit   LoadBalancer   172.17.73.145   104.198.26.189   80:31445/TCP   38s
mysql      ClusterIP      None            <none>           3306/TCP       4m53s
```

Access the minitwit application via the following URL:

```bash
echo "http://$(kubectl -n minitwit get service/minitwit -o yaml | yq '.status.loadBalancer.ingress[0].ip')/public"
```

## Docker Image Creation

```bash
docker buildx build --platform=linux/amd64 . -t minitwit
docker tag `docker images | grep ^minitwit | awk '{print $3}'` michaelhaigh/minitwit:0.1.0
docker push michaelhaigh/minitwit:0.1.0
```
