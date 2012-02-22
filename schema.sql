drop table if exists users;
drop table if exists items;
create table users (
  id integer primary key autoincrement,
  token string not null,
  url string
);
create table items (
  id integer primary key autoincrement,
  user_id integer not null,
  file_id integer not null
);