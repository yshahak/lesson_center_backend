import 'package:aqueduct/aqueduct.dart';

class Category extends ManagedObject<Categories> implements Categories {}

class Categories {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.integer, autoincrement: false)
  int id;
  @Column(nullable: false)
  int originalId;
  @Column(nullable: false)
  int sourceId;
  @Column(nullable: false)
  int totalCount;
  @Column(nullable: false)
  String category;
  @Column(nullable: false)
  int insertedat;
  @Column(nullable: false)
  int updatedat;
}
var table = '''
create table categories(
  id INTEGER NOT NULL PRIMARY KEY,
  category varchar(60) NOT NULL
   insertedat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
''';