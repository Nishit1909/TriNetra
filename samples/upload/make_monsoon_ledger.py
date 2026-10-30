"""Fictional demo case 'Operation Monsoon Ledger' for testing ingestion. All people and events are invented."""
import csv, random, zipfile, io, os
random.seed(2026)
import pathlib
OUT = str(pathlib.Path(__file__).resolve().parent / 'generated')
people = [
 # id, name, department (cell/role in the fictional story)
 ("OM01","Rakesh Venkat","Finance"),        # hidden coordinator: meets many, emails few
 ("OM02","Farah Siddiqui","Finance"),
 ("OM03","Deepak Nair","Logistics"),
 ("OM04","Sunil Rao","Logistics"),
 ("OM05","Meena Pillai","Logistics"),
 ("OM06","Arvind Joshi","Port Operations"),
 ("OM07","Kiran Desai","Port Operations"),
 ("OM08","Vikram Shetty","Port Operations"),
 ("OM09","Lakshmi Iyer","Accounts"),
 ("OM10","Naveen Gowda","Accounts"),
 ("OM11","Priya Menon","Accounts"),
 ("OM12","Imran Qureshi","Transport"),
 ("OM13","Joseph D'Souza","Transport"),
 ("OM14","Harish Kumar","Transport"),
 ("OM15","Anita Rao","Customs Liaison"),
 ("OM16","Suresh Babu","Customs Liaison"),     # bridge between port and finance
 ("OM17","Divya Hegde","Legal"),
 ("OM18","Manoj Patil","Legal"),
 ("OM19","Rohit Kulkarni","Warehousing"),
 ("OM20","Sneha Reddy","Warehousing"),
 ("OM21","Ganesh Murthy","Warehousing"),
 ("OM22","Asha Rao","Administration"),          # same surname, different person
 ("OM23","Tarun Bhat","Administration"),
 ("OM24","Kavitha Shenoy","Administration"),
 ("OM25","Ravi Shankar","External Supplier"),
 ("OM26","Nisha Kapoor","External Supplier"),
 ("OM27","Ajay Malhotra","External Supplier"),
 ("OM28","Pooja Agarwal","Auditor"),
 ("OM29","Sameer Khan","Auditor"),
 ("OM30","Latha Krishnan","Auditor"),
]
ids=[p[0] for p in people]; dept={p[0]:p[2] for p in people}
rels=[]
def add(a,b,t,w=1): rels.append((a,b,t,w))
# dense ties inside departments (operations / logistics etc.)
by={}
for i,d in dept.items(): by.setdefault(d,[]).append(i)
for d,m in by.items():
    for i in range(len(m)):
        for j in range(i+1,len(m)):
            if random.random()<0.7: add(m[i],m[j],"OPERATIONS")
# coordinator OM01 meets one person in many cells (in person, not by email)
for x in ["OM03","OM06","OM09","OM12","OM16","OM19","OM25"]: add("OM01",x,"MEETINGS",2)
# bridge OM16 links customs, port and finance
for x in ["OM06","OM07","OM02","OM15","OM12"]: add("OM16",x,"LOGISTICS")
# finance flows
for a,b in [("OM02","OM09"),("OM02","OM25"),("OM09","OM26"),("OM10","OM27"),("OM01","OM02")]: add(a,b,"BUSINESS&FINANCE",2)
# family / friendship
add("OM04","OM13","KINSHIP"); add("OM08","OM20","FRIENDSHIP"); add("OM11","OM24","FRIENDSHIP"); add("OM17","OM18","FRIENDSHIP")
# auditors only lightly connected
add("OM28","OM29","OPERATIONS"); add("OM29","OM30","OPERATIONS"); add("OM28","OM10","MEETINGS")
# communications (emails/messages): normal chatter + a few broadcasts; OM01 rarely writes directly
comms=[]; cid=0
start=[2026,9,1]
def ts(day,h,m): return f"2026-09-{day:02d} {h:02d}:{m:02d}:00"
pairs=[(a,b) for a,b,t,w in rels if t in ("OPERATIONS","LOGISTICS","BUSINESS&FINANCE") and "OM01" not in (a,b)]
for _ in range(220):
    a,b=random.choice(pairs)
    if random.random()<0.5: a,b=b,a
    cid+=1
    comms.append((f"MSG{cid:04d}",a,b,ts(random.randint(1,28),random.randint(8,20),random.randint(0,59)),
                  random.choice(["Shipment schedule","Invoice follow-up","Gate pass","Warehouse slot","Payment status","Customs paperwork","Truck availability"]),1))
# broadcasts from admin to everyone (should carry no relationship strength)
for k,day in enumerate([3,15,27]):
    for r in ids:
        if r=="OM22": continue
        cid+=1
        comms.append((f"MSG{cid:04d}","OM22",r,ts(day,9,30),["All-staff: office closed Friday","All-staff: new ID cards","All-staff: Diwali schedule"][k],len(ids)-1))
# the coordinator only ever sends two short direct messages
comms.append((f"MSG{cid+1:04d}","OM01","OM02",ts(10,22,41),"call me",1))
comms.append((f"MSG{cid+2:04d}","OM01","OM16",ts(19,23,5),"tomorrow",1))

def write(path, header, rows):
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(header); w.writerows(rows)
good=os.path.join(OUT,"monsoon_ledger"); os.makedirs(good,exist_ok=True)
write(f"{good}/persons.csv",["person_id","display_name","department","job_title"],[(i,n,d,"") for i,n,d in people])
write(f"{good}/relationships.csv",["person_a","person_b","relationship_type","weight","evidence_count"],[(a,b,t,w,1) for a,b,t,w in rels])
write(f"{good}/communications.csv",["communication_id","source_person_id","target_person_id","sent_at","subject","recipient_count"],comms)
with zipfile.ZipFile(f"{OUT}/monsoon_ledger_case.zip","w",zipfile.ZIP_DEFLATED) as z:
    for fn in ["persons.csv","relationships.csv","communications.csv"]: z.write(f"{good}/{fn}",fn)

# deliberately broken copy for testing validation errors
bad=os.path.join(OUT,"monsoon_ledger_broken"); os.makedirs(bad,exist_ok=True)
bp=[(i,n,d,"") for i,n,d in people]+[("OM05","Duplicate Meena","Logistics","")]     # duplicate ID
write(f"{bad}/persons.csv",["person_id","display_name","department","job_title"],bp)
br=[(a,b,t,w,1) for a,b,t,w in rels[:20]]+[("OM03","OM99","MEETINGS",1,1),("OM07","OM07","OPERATIONS",1,1),("OM08","OM09","FRIENDSHIP",-2,1)]
write(f"{bad}/relationships.csv",["person_a","person_b","relationship_type","weight","evidence_count"],br)
write(f"{bad}/communications.csv",["communication_id","source_person_id","target_person_id","sent_at","subject","recipient_count"],
      comms[:10]+[("MSGBAD1","OM01","OM02","not-a-date","x",1)])
with zipfile.ZipFile(f"{OUT}/monsoon_ledger_BROKEN.zip","w",zipfile.ZIP_DEFLATED) as z:
    for fn in ["persons.csv","relationships.csv","communications.csv"]: z.write(f"{bad}/{fn}",fn)
print(len(people),"people",len(rels),"relationships",len(comms),"communications")
