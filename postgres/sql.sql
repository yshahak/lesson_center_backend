CREATE TABLE lessons (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    title text,
    categoryid INTEGER,
    seriesid INTEGER,
    ravid INTEGER,
    datestr varchar(60),
    duration INTEGER,
    videourl text,
    audiourl text,
    "timestamp" INTEGER,
    insertedat timestamptz NOT NULL DEFAULT now(),
    updatedat timestamptz NOT NULL DEFAULT now(),
);
CREATE TABLE categories (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    category varchar(60) NOT NULL,
    insertedat timestamptz NOT NULL DEFAULT now(),
    updatedat timestamptz NOT NULL DEFAULT now(),
);
CREATE TABLE series (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    serie varchar(80) NOT NULL,
    insertedat timestamptz NOT NULL DEFAULT now(),
    updatedat timestamptz NOT NULL DEFAULT now(),
);
CREATE TABLE ravs (
    id INTEGER NOT NULL PRIMARY KEY,
    originalid INTEGER NOT NULL,
    sourceid INTEGER NOT NULL,
    totalcount INTEGER NOT NULL DEFAULT 0,
    rav varchar(60) NOT NULL,
    insertedat timestamptz NOT NULL DEFAULT now(),
    updatedat timestamptz NOT NULL DEFAULT now(),
);
CREATE TABLE labels(
    id SERIAL PRIMARY KEY,
    label varchar(60) NOT NULL,
    sourceid int NOT NULL,
    lessonid int NOT NULL,
    insertedat timestamptz NOT NULL DEFAULT now(),
    updatedat timestamptz NOT NULL DEFAULT now(),
);

CREATE OR REPLACE FUNCTION function_incrementer() RETURNS TRIGGER AS $BODY$
BEGIN
    UPDATE ravs SET totalcount = totalcount + 1, updatedat = now()
    WHERE id = new.ravid;
    UPDATE series SET totalcount = totalcount + 1, updatedat = now()
    WHERE id = new.seriesid;
    UPDATE categories SET totalcount = totalcount + 1, updatedat = now()
    WHERE id = new.categoryid;
    RETURN new;
END;
$BODY$ language plpgsql;

CREATE OR REPLACE FUNCTION function_update_inserted_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updatedat = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trig_incrementer
     AFTER INSERT ON lessons
     FOR EACH ROW
     EXECUTE PROCEDURE function_incrementer();

CREATE TRIGGER trig_set_timestamp
BEFORE UPDATE ON lessons
FOR EACH ROW
EXECUTE PROCEDURE function_update_inserted_at();

alter table lessons ALTER COLUMN updatedat TYPE timestamptz USING to_timestamp("updatedat");
alter table lessons ALTER COLUMN updatedat SET DEFAULT now();
alter table lessons ALTER COLUMN updatedat SET NOT NULL;
alter table categories add column updatedat timestamptz NOT NULL DEFAULT now();
--insert into lessons(
--    id,sourceid,originalid,title,categoryid,seriesid,ravid,"videourl","audiourl",datestr,duration,"timestamp","insertedat","updatedat")
--    values(4242424242,2,21263, 'title',62568005,41167770,29105323,'','','',0,0,0,0);