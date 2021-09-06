import tkinter as tk
from tkinter import Button, Tk
import random
import json
import pickle

baseColors = [
	('R', (0xFF, 0x00, 0x00)),
	('O', (0xFF, 0x7F, 0x00)),
	('Y', (0xFF, 0xFF, 0x00)),
	('G', (0x00, 0xFF, 0x00)),
	('C', (0x00, 0xFF, 0xFF)),
	('B', (0x00, 0x00, 0xFF)),
	#('I', (0x4B, 0x00, 0x82)),
	#('V', (0xEE, 0x82, 0xEE)),
	('M', (0xFF, 0x00, 0xFF)),
	('K', (0x00, 0x00, 0x00)),
	('L', (0x7F, 0x7F, 0x7F)),
	('W', (0xFF, 0xFF, 0xFF))
]

palGradient = [
	0x00, 0x33, 0x66, 0x99, 0xCC, 0xFF
#	0x00, 0x3F, 0x7F, 0xFF
]

gradientLen = len(palGradient)
numColors = gradientLen * gradientLen * gradientLen

def getPalColor(idx: int) -> tuple[int, int, int]:
	idx = max(min(idx, numColors), 0)
	b = idx % gradientLen
	g = (idx // gradientLen) % gradientLen
	r = idx // (gradientLen * gradientLen)
	return(palGradient[r], palGradient[g], palGradient[b])

def colToText(col: tuple[int, int, int]):
	return "#{:02x}{:02x}{:02x}".format(col[0], col[1], col[2])

def nextColor() -> bool:
	if (not remainingColors):
		curColor[0] = None
		processedColors.sort(reverse=False, key=lambda x: x[1][2] + (x[1][1]<<8) + (x[1][0]<<16))
		with open("palette.txt", "wt", encoding='utf8') as outFile:
			print("[", file=outFile)
			s = ",\n".join("\t('{0}', (0x{1:02x}, 0x{2:02x}, 0x{3:02x}))".format(x[0], x[1][0], x[1][1], x[1][2]) for x in processedColors)
			print(s, file=outFile)
			print("]", file=outFile)
		with open("palette.json", "w", encoding='utf8') as outFile:
			json.dump(processedColors, outFile, indent='\t')
		return
		pass

	colIdx = random.choice(range(len(remainingColors)))
	col = remainingColors[colIdx]
	print(col)
	curColor[0]=col
	disp.configure(bg=colToText(col))
	del remainingColors[colIdx]
	print("remaining({1}): {0}".format(remainingColors, len(remainingColors)))
	print("current: {0}".format(col))
	pass

def selectColor(index: int):
	if (curColor[0]):
		processedColors.append((baseColors[index][0], curColor[0]))
		print("processed({0}): {1}".format(len(processedColors), processedColors))
	nextColor()
	pass

remainingColors=[getPalColor(x) for x in range(numColors)]
print(remainingColors)
processedColors=[]
curColor=[None]

root = Tk()
root.title("Pal selector")
root.geometry("640x480")

vertFrame = tk.Frame(master=root)
vertFrame.pack(fill=tk.X)

label=tk.Label(text="Select most similar color", master=vertFrame)
label.pack(fill=tk.X, expand=True)

disp=tk.Frame(master=vertFrame, width=320, height=360, bg='red')
disp.pack(fill=tk.BOTH, expand=True)

horFrame = tk.Frame(master=root)
horFrame.pack(fill=tk.BOTH, expand=True)


buttons = []
for i in range(len(baseColors)):
	col = baseColors[i]
	hexCol = "#{:02x}{:02x}{:02x}".format(col[1][0], col[1][1], col[1][2])
	print(hexCol)
	btn = tk.Button(master=horFrame, bg=hexCol, width=6, height=3, command=lambda idx=i: selectColor(idx))
	btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
	buttons.append(btn)

nextColor()
root.mainloop()