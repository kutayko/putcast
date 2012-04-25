drop table if exists users;
drop table if exists items;
drop table if exists feeds;
create table users (
  id integer primary key autoincrement,
  token string not null
);

create table items (
  id integer primary key autoincrement,
  user_id integer not null,
  folder_id integer not null
);

create table feeds (
    id integer primary key autoincrement,
    user_id integer not null,
    name varchar not null,
    audio boolean default 1,
    video boolean default 0
);