drop table if exists users;
drop table if exists items;
drop table if exists feeds;

create table items (
  id integer primary key autoincrement,
  feed_token varchar not null,
  folder_id integer not null
);

create table feeds (
    id integer primary key autoincrement,
    user_token varchar not null,
    name varchar not null,
    feed_token varchar not null,
    audio boolean default 1,
    video boolean default 0
);