CREATE TABLE lessons (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    title varchar(120),
    categoryid INTEGER,
    seriesid INTEGER,
    ravid INTEGER,
    datestr varchar(60),
    duration INTEGER,
    videourl varchar(120),
    audiourl varchar(120),
    "timestamp" INTEGER,
    insertedat INTEGER,
    updatedat INTEGER
);
CREATE TABLE categories (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    category varchar(60) NOT NULL
);
CREATE TABLE series (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    serie varchar(80) NOT NULL
);
CREATE TABLE ravs (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    rav varchar(60) NOT NULL
);
CREATE TABLE labels(
  id SERIAL PRIMARY KEY,
  label varchar(60) NOT NULL,
  sourceid int NOT NULL,
  lessonid int NOT NULL
);

CREATE OR REPLACE FUNCTION function_incrementer() RETURNS TRIGGER AS
$BODY$
BEGIN
    UPDATE ravs SET totalcount = totalcount + 1
    WHERE id = new.ravid;
    UPDATE series SET totalcount = totalcount + 1
    WHERE id = new.seriesid;
    UPDATE categories SET totalcount = totalcount + 1
    WHERE id = new.categoryid;
    RETURN new;
END;
$BODY$
language plpgsql;

CREATE TRIGGER trig_incrementer
     AFTER INSERT ON lessons
     FOR EACH ROW
     EXECUTE PROCEDURE function_incrementer();

--insert into lessons(
--    id,sourceid,originalid,title,categoryid,seriesid,ravid,"videourl","audiourl",datestr,duration,"timestamp","insertedat","updatedat")
--    values(4242424242,2,21263, 'title',62568005,41167770,29105323,'','','',0,0,0,0);