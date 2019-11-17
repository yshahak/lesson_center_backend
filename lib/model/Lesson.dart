import 'package:aqueduct/aqueduct.dart';
import 'package:lessons_center_common/lessons_center_common.dart';

const String columnId = 'id';
const String columnTitle = 'title';
const String columnLabel = 'label';
const String columnSubjectId = 'subjectId';
const String columnSubject = 'subject';
const String columnSeriesId = 'seriesId';
const String columnSeries = 'series';
const String columnLength = 'length';
const String columnDate = 'dateStr';
const String columnRavId = 'ravId';
const String columnRav = 'rav';
const String columnVideoUrl = 'videoUrl';
const String columnAudioUrl = 'audioUrl';
const String columnTimestamp = 'timestamp';
const String columnSource = 'source';

class Lesson extends ManagedObject<Lessons> implements Lessons {}

class Lessons {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.bigInteger, autoincrement: false)
  int id;
  @Column(nullable: false)
  String source;
  @Column(nullable: true)
  String title;
  @Column(nullable: true)
  String label;
  @Column(nullable: true)
  int subjectId;
  @Column(nullable: true)
  String subject;
  @Column(nullable: true)
  int seriesId;
  @Column(nullable: true)
  String series;
  @Column(nullable: true)
  String dateStr;
  @Column(nullable: true)
  int ravId;
  @Column(nullable: true)
  String rav;
  @Column(nullable: true)
  String length;
  @Column(nullable: true)
  String videoUrl;
  @Column(nullable: true)
  String audioUrl;
  @Column(nullable: true)
  int timestamp;
  @Column(nullable: true)
  int insertedAt;
  @Column(nullable: false)
  int updatedAt;
}
