lineList = [line.rstrip('\n') for line in open("./Mozart output")]

def isnumeric(c):
	flag = True
	for i in range(0, len(c)):
		if ord(c[i]) >= 48 and ord(c[i]) < 58:
			pass
		else:
			flag = False
	return flag

def atoi(c):
	if ord(c) >= 48 and ord(c) < 58:
		return ord(c) - 48

listOfNotes = []
minNote = 1000
maxNote = 0

minVelocity = 1000
maxVelocity = 0

minTime = 10000
maxTime = 0


t = 0
for line in lineList:
	numericLine = ""
	noteAttribs = []
	if line[0:7] == "note_on":
		numericLine += "1 " 
		noteAttribs.append(1)
	elif line[0:8] == "note_off":
		numericLine += "0 "
		noteAttribs.append(0)
	else:
		continue	
	for c in range(0,len(line)):
		if line[c:c+5] == "note=":
			l = 0
			note = line[c+5]
			while isnumeric(line[c+5:c+5+l]):
				note = line[c+5:c+5+l]
				l += 1
			noteAttribs.append(int(note))
			
			if int(note) > maxNote:
				maxNote = int(note)
			if int(note) < minNote:
				minNote = int(note)
		if line[c:c+9] == "velocity=":
			l = 0
			velocity = line[c+9]
			while isnumeric(line[c+9:c+9+l]):
				velocity = line[c+9:c+9+l]
				l += 1
			noteAttribs.append(int(velocity))
			
			if int(velocity) > maxVelocity:
				maxVelocity = int(velocity)
			if int(velocity) < minVelocity:
				minVelocity = int(velocity)
		if line[c:c+5] == "time=":
			l = 0
			time = line[c+5]
			while isnumeric(line[c+5:c+5+l]) and c+5+l <= len(line):
				time = line[c+5:c+5+l]
				l += 1
			noteAttribs.append(int(time))
		
			if int(time) > maxTime:
				maxTime = int(time)
			if int(time) < minTime:
				minTime = int(time)

	noteAttribs.append(t)
	t += 1
	listOfNotes.append(noteAttribs)
#print listOfNotes[t-1]

for line in listOfNotes:
	line[1] = float(line[1]-minNote)/maxNote
	line[2] = float(line[2]-minVelocity)/maxVelocity
	line[3] = float(line[3]-minTime)/maxTime
	line[4] = float(line[4])/(t-1)
	print line

print "<", minNote, maxNote, ">"
print "<", minVelocity, maxVelocity, ">"
print "<", minTime, maxTime, ">"
print "<", 0, t-1, ">"
