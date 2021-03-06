import os, json, sys
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy import create_engine
from sqlalchemy import tuple_
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from pathlib import Path
from datetime import datetime
import hashlib
import time

from PIL import Image
import dhash
import pytesseract
import numpy as np

from sqlalchemy.sql import exists
from sqlalchemy.sql.expression import func

from itertools import zip_longest, groupby

import argparse
import subprocess
import multiprocessing as mp
from typing import Optional

Base = declarative_base()

DB_PATH = 'imgdb.db'
DEFAULT_HASH = ""

class FileData(Base):
	__tablename__ = 'files'

	id = Column(Integer, primary_key=True)
	path = Column(String, unique=True)
	size = Column(Integer, index=True)
	ctime = Column(DateTime)
	mtime = Column(DateTime)

	hash = Column(String, index=True)
	def __str__(self) -> str:
		return "FileData: {{id: {0}, path: '{1}', size: {2}, ctime: {3}, mtime: {4}, hash: {5}}}".format(
			self.id, self.path, self.size, self.ctime, self.mtime, self.hash
		)

class ScanFileData(Base):
	__tablename__ = 'scanfiles'

	id = Column(Integer, primary_key=True)
	path = Column(String, unique=True)
	size = Column(Integer)
	ctime = Column(DateTime)
	mtime = Column(DateTime)

	def __str__(self) -> str:
		return "ScanFileData: {{id: {0}, path: '{1}', size: {2}, ctime: {3}, mtime: {4}}}".format(
			self.id, self.path, self.size, self.ctime, self.mtime
		)

class DHashData(Base):
	__tablename__ = 'dhashes'
	id = Column(Integer, primary_key=True)
	hash = Column(String, index=True)
	size = Column(Integer, index=True)

	hashSize = Column(Integer)
	dhash = Column(String)
	def __str__(self) -> str:
		return "DHashData: {{id: {0}, hash: '{1}', size: {2}, hashSize: {3}, dhash: {4}}}".format(
			self.id, self.hash, self.size, self.hashSize, self.dhash
		)

class PaletteData(Base):
	__tablename__ = 'palettes'
	id = Column(Integer, primary_key=True)
	hash = Column(String, index=True)
	size = Column(Integer, index=True)

	palette = Column(String, index=True)
	def __str__(self) -> str:
		return "PaletteData: {{id: {0}, hash: '{1}', size: {2}, palette: {3}}}".format(
			self.id, self.hash, self.size, self.palette
		)

class OcrData(Base):
	__tablename__ = 'ocr'
	id = Column(Integer, primary_key=True)
	hash = Column(String, index=True)
	size = Column(Integer, index=True)

	lang = Column(String)
	text = Column(String, index=True)
	def __str__(self) -> str:
		return "OcrData: {{id: {0}, hash: '{1}', size: {2}, lang: {3}, text: {4}}}".format(
			self.id, self.hash, self.size, self.lang, self.text
		)

class OperationInterruptedException(Exception):
	pass

class Config:
	KEY_DB_PATH = 'dbpath'
	KEY_PATHS = 'paths'
	KEY_TESSCMD = 'tesscmd'
	KEY_EXCLUDE_PATHS = 'excludePaths'
	KEY_EXTENSIONS = 'extensions'
	DEFAULT_PATH = 'imgdbcfg.json'
	def save(self, path) -> None:
		with open(path, mode="w", encoding="utf8") as outFile:
			data = {}
			data[Config.KEY_PATHS] = self.paths
			data[Config.KEY_DB_PATH] = self.dbpath
			data[Config.KEY_TESSCMD] = self.tesscmd
			data[Config.KEY_EXCLUDE_PATHS] = self.excludePaths
			data[Config.KEY_EXTENSIONS] = self.extensions

			json.dump(data, outFile, indent='\t')

	def load(self, path) -> None:
		with open(path, mode="r", encoding='utf8') as inFile:
			data = json.load(inFile)
			self.paths = list(data[Config.KEY_PATHS])
			self.dbpath = data[Config.KEY_DB_PATH]
			self.tesscmd = data[Config.KEY_TESSCMD]
			self.excludePaths = list(data[Config.KEY_EXCLUDE_PATHS])
			self.extensions = list(data[Config.KEY_EXTENSIONS])

	def getConfig():
		path = Config.DEFAULT_PATH
		result = Config()
		if os.path.isfile(path):
			result.load(path)
			return result
		result.save(path)
		return result

	def isExcludedPath(self, path: str):
		childPath = Path(path)
		for cur in self.excludePaths:
			curPath = Path(cur)
			if childPath.is_relative_to(curPath):
				return True
		return False

	def isSupportedExt(self, filePath) -> bool:
		split = os.path.splitext(filePath)
		if (len(split) != 2):
			return False
		splitExt = split[1].lower()		
		for curExt in self.extensions:
			if curExt.lower() == splitExt:
				return True
		return False

	def __init__(self) -> None:
		self.paths = ['img']
		self.dbpath = 'imgdb.db'
		self.tesscmd = ['tesseract']
		self.excludePaths = ['img/excluded']
		self.extensions = ['.png', '.tga', '.jpeg', '.jpg', '.bmp']
		pass
	pass

def getDigest(path: str):
	h = hashlib.sha256()
	blockSize = 1024 * 1024 * 10
	with open(path, "rb") as inFile:
		while True:
			chunk = inFile.read(blockSize)
			if not chunk:
				break
			h.update(chunk)
	return h.hexdigest()

def getDHash(path: str, size: int = 8):
	with Image.open(path) as img:
		row, col = dhash.dhash_row_col(img)
		return dhash.format_hex(row, col)

"""
letterPalette = [
	('K', (0x00, 0x00, 0x00)),
	('W', (0xFF, 0xFF, 0xFF)),
	('R', (0xFF, 0x00, 0x00)),
	('G', (0x00, 0xFF, 0x00)),
	('B', (0x00, 0x00, 0xFF)),
	('Y', (0xFF, 0xFF, 0x00)),
	('M', (0xFF, 0x00, 0xFF)),
	('C', (0x00, 0xFF, 0xFF)),
	('D', (0x3F, 0x3F, 0x3F)),
	('A', (0x7F, 0x7F, 0x7F)),
	('L', (0xBF, 0xBF, 0xBF))
]
"""
# letterPalette = [
# 	('K', (0x00, 0x00, 0x00)),
# 	('W', (0xFF, 0xFF, 0xFF)),

# 	# ('R', (0x7F, 0x00, 0x00)),
# 	# ('G', (0x00, 0x7F, 0x00)),
# 	# ('B', (0x00, 0x00, 0x7F)),

# 	# ('Y', (0x7F, 0x7F, 0x00)),
# 	# ('M', (0x7F, 0x00, 0x7F)),
# 	# ('C', (0x00, 0x7F, 0x7F)),

# 	('R', (0x3F, 0x00, 0x00)),
# 	('R', (0x7F, 0x00, 0x00)),
# 	('R', (0xFF, 0x00, 0x00)),
# 	('R', (0x7F, 0x3F, 0x3F)),
# 	('R', (0xFF, 0x3F, 0x3F)),
# 	('R', (0xFF, 0x7F, 0x7F)),

# 	('G', (0x00, 0x3F, 0x00)),
# 	('G', (0x00, 0x7F, 0x00)),
# 	('G', (0x00, 0xFF, 0x00)),
# 	('G', (0x3F, 0x7F, 0x3F)),
# 	('G', (0x3F, 0xFF, 0x3F)),
# 	('G', (0x7F, 0xFF, 0x7F)),

# 	('B', (0x00, 0x00, 0x3F)),
# 	('B', (0x00, 0x00, 0x7F)),
# 	('B', (0x00, 0x00, 0xFF)),
# 	('B', (0x3F, 0x3F, 0x7F)),
# 	('B', (0x3F, 0x3F, 0xFF)),
# 	('B', (0x7F, 0x7F, 0xFF)),

# 	('Y', (0x3F, 0x3F, 0x00)),
# 	('Y', (0x7F, 0x7F, 0x00)),
# 	('Y', (0xFF, 0xFF, 0x00)),
# 	('Y', (0x7F, 0x7F, 0x3F)),
# 	('Y', (0xFF, 0xFF, 0x3F)),
# 	('Y', (0xFF, 0xFF, 0x7F)),

# 	('M', (0x3F, 0x00, 0x3F)),
# 	('M', (0x7F, 0x00, 0x7F)),
# 	('M', (0xFF, 0x00, 0xFF)),
# 	('M', (0x7F, 0x3F, 0x7F)),
# 	('M', (0xFF, 0x3F, 0xFF)),
# 	('M', (0xFF, 0x7F, 0xFF)),

# 	('C', (0x00, 0x3F, 0x3F)),
# 	('C', (0x00, 0x7F, 0x7F)),
# 	('C', (0x00, 0xFF, 0xFF)),
# 	('C', (0x3F, 0x7F, 0x7F)),
# 	('C', (0x3F, 0xFF, 0xFF)),
# 	('C', (0x7F, 0xFF, 0xFF)),

# 	('D', (0x3F, 0x3F, 0x3F)),
# 	('A', (0x7F, 0x7F, 0x7F)),
# 	('L', (0xBF, 0xBF, 0xBF))
# ]

letterPalette = [
	('K', (0x00, 0x00, 0x00)),
	('B', (0x00, 0x00, 0x33)),
	('B', (0x00, 0x00, 0x66)),
	('B', (0x00, 0x00, 0x99)),
	('B', (0x00, 0x00, 0xcc)),
	('B', (0x00, 0x00, 0xff)),
	('G', (0x00, 0x33, 0x00)),
	('G', (0x00, 0x33, 0x33)),
	('B', (0x00, 0x33, 0x66)),
	('B', (0x00, 0x33, 0x99)),
	('B', (0x00, 0x33, 0xcc)),
	('B', (0x00, 0x33, 0xff)),
	('G', (0x00, 0x66, 0x00)),
	('G', (0x00, 0x66, 0x33)),
	('G', (0x00, 0x66, 0x66)),
	('B', (0x00, 0x66, 0x99)),
	('B', (0x00, 0x66, 0xcc)),
	('B', (0x00, 0x66, 0xff)),
	('G', (0x00, 0x99, 0x00)),
	('G', (0x00, 0x99, 0x33)),
	('C', (0x00, 0x99, 0x66)),
	('C', (0x00, 0x99, 0x99)),
	('C', (0x00, 0x99, 0xcc)),
	('B', (0x00, 0x99, 0xff)),
	('G', (0x00, 0xcc, 0x00)),
	('G', (0x00, 0xcc, 0x33)),
	('G', (0x00, 0xcc, 0x66)),
	('G', (0x00, 0xcc, 0x99)),
	('C', (0x00, 0xcc, 0xcc)),
	('C', (0x00, 0xcc, 0xff)),
	('G', (0x00, 0xff, 0x00)),
	('G', (0x00, 0xff, 0x33)),
	('G', (0x00, 0xff, 0x66)),
	('G', (0x00, 0xff, 0x99)),
	('C', (0x00, 0xff, 0xcc)),
	('C', (0x00, 0xff, 0xff)),
	('O', (0x33, 0x00, 0x00)),
	('M', (0x33, 0x00, 0x33)),
	('M', (0x33, 0x00, 0x66)),
	('B', (0x33, 0x00, 0x99)),
	('B', (0x33, 0x00, 0xcc)),
	('B', (0x33, 0x00, 0xff)),
	('G', (0x33, 0x33, 0x00)),
	('L', (0x33, 0x33, 0x33)),
	('B', (0x33, 0x33, 0x66)),
	('B', (0x33, 0x33, 0x99)),
	('B', (0x33, 0x33, 0xcc)),
	('B', (0x33, 0x33, 0xff)),
	('G', (0x33, 0x66, 0x00)),
	('G', (0x33, 0x66, 0x33)),
	('G', (0x33, 0x66, 0x66)),
	('B', (0x33, 0x66, 0x99)),
	('B', (0x33, 0x66, 0xcc)),
	('B', (0x33, 0x66, 0xff)),
	('G', (0x33, 0x99, 0x00)),
	('G', (0x33, 0x99, 0x33)),
	('G', (0x33, 0x99, 0x66)),
	('C', (0x33, 0x99, 0x99)),
	('C', (0x33, 0x99, 0xcc)),
	('B', (0x33, 0x99, 0xff)),
	('G', (0x33, 0xcc, 0x00)),
	('G', (0x33, 0xcc, 0x33)),
	('G', (0x33, 0xcc, 0x66)),
	('G', (0x33, 0xcc, 0x99)),
	('C', (0x33, 0xcc, 0xcc)),
	('C', (0x33, 0xcc, 0xff)),
	('G', (0x33, 0xff, 0x00)),
	('G', (0x33, 0xff, 0x33)),
	('G', (0x33, 0xff, 0x66)),
	('G', (0x33, 0xff, 0x99)),
	('C', (0x33, 0xff, 0xcc)),
	('C', (0x33, 0xff, 0xff)),
	('R', (0x66, 0x00, 0x00)),
	('M', (0x66, 0x00, 0x33)),
	('M', (0x66, 0x00, 0x66)),
	('M', (0x66, 0x00, 0x99)),
	('M', (0x66, 0x00, 0xcc)),
	('B', (0x66, 0x00, 0xff)),
	('O', (0x66, 0x33, 0x00)),
	('R', (0x66, 0x33, 0x33)),
	('M', (0x66, 0x33, 0x66)),
	('M', (0x66, 0x33, 0x99)),
	('M', (0x66, 0x33, 0xcc)),
	('B', (0x66, 0x33, 0xff)),
	('G', (0x66, 0x66, 0x00)),
	('G', (0x66, 0x66, 0x33)),
	('L', (0x66, 0x66, 0x66)),
	('B', (0x66, 0x66, 0x99)),
	('B', (0x66, 0x66, 0xcc)),
	('B', (0x66, 0x66, 0xff)),
	('G', (0x66, 0x99, 0x00)),
	('G', (0x66, 0x99, 0x33)),
	('G', (0x66, 0x99, 0x66)),
	('C', (0x66, 0x99, 0x99)),
	('C', (0x66, 0x99, 0xcc)),
	('B', (0x66, 0x99, 0xff)),
	('G', (0x66, 0xcc, 0x00)),
	('G', (0x66, 0xcc, 0x33)),
	('G', (0x66, 0xcc, 0x66)),
	('C', (0x66, 0xcc, 0x99)),
	('C', (0x66, 0xcc, 0xcc)),
	('C', (0x66, 0xcc, 0xff)),
	('G', (0x66, 0xff, 0x00)),
	('G', (0x66, 0xff, 0x33)),
	('G', (0x66, 0xff, 0x66)),
	('G', (0x66, 0xff, 0x99)),
	('C', (0x66, 0xff, 0xcc)),
	('C', (0x66, 0xff, 0xff)),
	('R', (0x99, 0x00, 0x00)),
	('R', (0x99, 0x00, 0x33)),
	('M', (0x99, 0x00, 0x66)),
	('M', (0x99, 0x00, 0x99)),
	('M', (0x99, 0x00, 0xcc)),
	('M', (0x99, 0x00, 0xff)),
	('R', (0x99, 0x33, 0x00)),
	('R', (0x99, 0x33, 0x33)),
	('M', (0x99, 0x33, 0x66)),
	('M', (0x99, 0x33, 0x99)),
	('M', (0x99, 0x33, 0xcc)),
	('M', (0x99, 0x33, 0xff)),
	('O', (0x99, 0x66, 0x00)),
	('O', (0x99, 0x66, 0x33)),
	('M', (0x99, 0x66, 0x66)),
	('M', (0x99, 0x66, 0x99)),
	('M', (0x99, 0x66, 0xcc)),
	('B', (0x99, 0x66, 0xff)),
	('Y', (0x99, 0x99, 0x00)),
	('Y', (0x99, 0x99, 0x33)),
	('L', (0x99, 0x99, 0x66)),
	('L', (0x99, 0x99, 0x99)),
	('M', (0x99, 0x99, 0xcc)),
	('C', (0x99, 0x99, 0xff)),
	('G', (0x99, 0xcc, 0x00)),
	('G', (0x99, 0xcc, 0x33)),
	('G', (0x99, 0xcc, 0x66)),
	('G', (0x99, 0xcc, 0x99)),
	('C', (0x99, 0xcc, 0xcc)),
	('C', (0x99, 0xcc, 0xff)),
	('G', (0x99, 0xff, 0x00)),
	('G', (0x99, 0xff, 0x33)),
	('G', (0x99, 0xff, 0x66)),
	('G', (0x99, 0xff, 0x99)),
	('C', (0x99, 0xff, 0xcc)),
	('C', (0x99, 0xff, 0xff)),
	('R', (0xcc, 0x00, 0x00)),
	('R', (0xcc, 0x00, 0x33)),
	('R', (0xcc, 0x00, 0x66)),
	('M', (0xcc, 0x00, 0x99)),
	('M', (0xcc, 0x00, 0xcc)),
	('M', (0xcc, 0x00, 0xff)),
	('R', (0xcc, 0x33, 0x00)),
	('R', (0xcc, 0x33, 0x33)),
	('M', (0xcc, 0x33, 0x66)),
	('M', (0xcc, 0x33, 0x99)),
	('M', (0xcc, 0x33, 0xcc)),
	('M', (0xcc, 0x33, 0xff)),
	('O', (0xcc, 0x66, 0x00)),
	('O', (0xcc, 0x66, 0x33)),
	('R', (0xcc, 0x66, 0x66)),
	('M', (0xcc, 0x66, 0x99)),
	('M', (0xcc, 0x66, 0xcc)),
	('M', (0xcc, 0x66, 0xff)),
	('O', (0xcc, 0x99, 0x00)),
	('O', (0xcc, 0x99, 0x33)),
	('O', (0xcc, 0x99, 0x66)),
	('M', (0xcc, 0x99, 0x99)),
	('M', (0xcc, 0x99, 0xcc)),
	('M', (0xcc, 0x99, 0xff)),
	('Y', (0xcc, 0xcc, 0x00)),
	('Y', (0xcc, 0xcc, 0x33)),
	('Y', (0xcc, 0xcc, 0x66)),
	('Y', (0xcc, 0xcc, 0x99)),
	('L', (0xcc, 0xcc, 0xcc)),
	('C', (0xcc, 0xcc, 0xff)),
	('Y', (0xcc, 0xff, 0x00)),
	('Y', (0xcc, 0xff, 0x33)),
	('Y', (0xcc, 0xff, 0x66)),
	('G', (0xcc, 0xff, 0x99)),
	('G', (0xcc, 0xff, 0xcc)),
	('C', (0xcc, 0xff, 0xff)),
	('R', (0xff, 0x00, 0x00)),
	('R', (0xff, 0x00, 0x33)),
	('R', (0xff, 0x00, 0x66)),
	('M', (0xff, 0x00, 0x99)),
	('M', (0xff, 0x00, 0xcc)),
	('M', (0xff, 0x00, 0xff)),
	('R', (0xff, 0x33, 0x00)),
	('R', (0xff, 0x33, 0x33)),
	('R', (0xff, 0x33, 0x66)),
	('M', (0xff, 0x33, 0x99)),
	('K', (0xff, 0x33, 0xcc)),
	('M', (0xff, 0x33, 0xff)),
	('O', (0xff, 0x66, 0x00)),
	('O', (0xff, 0x66, 0x33)),
	('R', (0xff, 0x66, 0x66)),
	('M', (0xff, 0x66, 0x99)),
	('M', (0xff, 0x66, 0xcc)),
	('M', (0xff, 0x66, 0xff)),
	('O', (0xff, 0x99, 0x00)),
	('O', (0xff, 0x99, 0x33)),
	('O', (0xff, 0x99, 0x66)),
	('M', (0xff, 0x99, 0x99)),
	('M', (0xff, 0x99, 0xcc)),
	('M', (0xff, 0x99, 0xff)),
	('Y', (0xff, 0xcc, 0x00)),
	('Y', (0xff, 0xcc, 0x33)),
	('Y', (0xff, 0xcc, 0x66)),
	('Y', (0xff, 0xcc, 0x99)),
	('R', (0xff, 0xcc, 0xcc)),
	('M', (0xff, 0xcc, 0xff)),
	('Y', (0xff, 0xff, 0x00)),
	('Y', (0xff, 0xff, 0x33)),
	('Y', (0xff, 0xff, 0x66)),
	('Y', (0xff, 0xff, 0x99)),
	('Y', (0xff, 0xff, 0xcc)),
	('W', (0xff, 0xff, 0xff))
]

def getPaletteString(path: str) -> str:
	with Image.open(path) as img:
		palette = []
		for x in letterPalette:
			palette.extend(x[1])
		palette = palette + [0]*(768 - len(palette))
		
		palImg = Image.new('P', (1, 1))
		palImg.putpalette(palette)

		convImg = None

		#print("{0}: {1}".format(img.mode, path))
		if (img.mode in ['L', 'LA', 'CMYK', '1', 'P', 'RGBA']):
			tmpImg = img.convert('RGB')
			convImg = tmpImg.quantize(colors=len(letterPalette), palette=palImg, dither=0)
		else:
			convImg = img.quantize(colors=len(letterPalette), palette=palImg, dither=0)
		#convImg.show()
		unique, counts = np.unique(convImg, return_counts=True)
		total = sum(counts)
		cutoff = total*2/100

		zipped = zip_longest(unique, counts)
		zipped = list(zipped)
		if (len(zipped) > len(letterPalette)):
			print("invalid palette: {0} (len zipped: {1}). MOde: {2}".format(path, len(zipped), img.mode))
			#print(zipped, len(zipped))
			raise Exception("Algorithm error")
			
		#print(list(zipped))
		res = [(letterPalette[x[0]][0], x[1]) for x in zipped if x[1] > cutoff]

		letterCounts = {}
		for x in res:
			letterCounts[x[0]] = letterCounts.get(x[0], 0) + x[1]

		letters = list(letterCounts)
		letters.sort(key = lambda x: letterCounts.get(x, 0), reverse=True)

		result = "".join(letters)
		return result
		# print(letterCounts)
		# res = "".join(c[0] for c in groupby(res))
		# return res

def makeFileData(scanFile: ScanFileData) -> FileData:
	newData = FileData(
		path = scanFile.path,
		size = scanFile.size,
		mtime = scanFile.mtime,
		ctime = scanFile.ctime,

		hash = getDigest(scanFile.path)
	)
	return newData

def makeHashData(fileData: FileData) -> tuple[str, FileData]:
	try:
		return (fileData, getDigest(fileData.path))
	except KeyboardInterrupt:
		return None

def makeDHashData(data: tuple[FileData, int]) -> tuple[DHashData, str]:
	try:
		fileData = data[0]
		dhashSize = data[1]
		imgHash = getDHash(fileData.path, dhashSize)
		newData = DHashData(
			hash = fileData.hash,
			size = fileData.size,
			hashSize = dhashSize,
			dhash = imgHash
		)
		return (newData, fileData.path)
	except KeyboardInterrupt:
		return None

def makeOcrData(data: tuple[tuple[str, int, str], str, str, bool]) \
		-> tuple[Optional[tuple[str, str]], tuple[str, int, str], Optional[Exception]]:
	try:
		fileData = data[0]
		tessCmd = data[1]
		ocrLang = data[2]
		useFullData = data[3]

		filePath = fileData[0]
		fileSize = fileData[1]
		fileHash = fileData[2]

		with Image.open(filePath) as img:
			pytesseract.pytesseract.tesseract_cmd = tessCmd
			ocr = pytesseract.image_to_data(img, lang=ocrLang) if useFullData else pytesseract.image_to_string(img, lang=ocrLang) 
			# newData = OcrData(
			# 	size = fileData.size,
			# 	hash = fileData.hash,
			# 	lang = ocrLang,
			# 	text = ocr
			# )
			return ((ocr, ocrLang), fileData, None)
	except KeyboardInterrupt:
		return None
	except Exception as e:
		return (None, fileData, e)

def makePaletteData(fileData: FileData) \
		-> tuple[Optional[PaletteData], str, Optional[Exception]]:
	try:
		palString = getPaletteString(fileData.path)
		#print(palString)
		newData = PaletteData(
			size = fileData.size,
			hash = fileData.hash,
			palette = palString
		)
		#print(newData)
		return (newData, fileData.path, None)
	except KeyboardInterrupt:
		return None
	except Exception as e:
		return (None, fileData.path, e)

class DbProcessor:
	def scanFilesystem(self):
		self.session.query(ScanFileData).delete()
		print("scanning filesystem")
		for curPath in self.config.paths:
			for root, dirs, files in os.walk(curPath, topdown=True):
				if self.config.isExcludedPath(root):
					continue
				for curFile in files:
					curFilePath = os.path.join(root, curFile)
					if not self.config.isSupportedExt(curFilePath):
						continue
					print("scanning: {0}".format(curFilePath))
					fileObj = Path(curFilePath)
					if not fileObj.exists:
						print("File {0} not found".format(curFilePath))
						continue
					fileStat = fileObj.stat()

					scanData = ScanFileData(
						path = curFilePath,
						size = fileStat.st_size,
						ctime = datetime.fromtimestamp(fileStat.st_ctime),
						mtime = datetime.fromtimestamp(fileStat.st_mtime)
					)
					self.session.add(scanData)

		print("scan done, building queries")

		newFiles = self.session.query(ScanFileData).filter(~ exists().where(FileData.path == ScanFileData.path))
		deletedFiles = self.session.query(FileData).filter(~ exists().where(FileData.path == ScanFileData.path))
		changedFiles = self.session.query(ScanFileData, FileData).filter(ScanFileData.path == FileData.path).filter(
			(ScanFileData.size != FileData.size) or 
			(ScanFileData.mtime != FileData.mtime) or 
			(ScanFileData.ctime != FileData.ctime)
		)

		numNewFiles = newFiles.count()
		print("new files: {0}".format(numNewFiles))
		numDeletedFiles = deletedFiles.count()
		print("deleted files: {0}".format(numDeletedFiles))
		numChangedFiles = changedFiles.count()
		print("changed files: {0}".format(numChangedFiles))

		print("processing deleted files: {0}".format(deletedFiles.count()))
		fileIndex = 0
		for f in deletedFiles.all():
			fileIndex += 1
			print("deleting file {0}/{1}".format(fileIndex, numDeletedFiles))
			self.session.delete(f)

		print("processing changed files: {0}".format(changedFiles.count()))
		fileIndex = 0
		for scanFile, file in changedFiles.all():
			fileIndex += 1
			print("processing changed file {1}/{2}: {0}".format(scanFile.path, fileIndex, numNewFiles))
			file.ctime = scanFile.ctime
			file.mtime = scanFile.mtime
			file.size = scanFile.size
			file.hash = DEFAULT_HASH

		print("processing new files: {0}".format(newFiles.count()))
		fileIndex = 0
		#for newData in pool.imap(makeFileData, newFiles.all()):
		for scanFile in newFiles.all():
			fileIndex += 1
			print("adding new file {1}/{2}: {0}".format(scanFile.path, fileIndex, numNewFiles))
			newData = FileData(
				path = scanFile.path,
				size = scanFile.size,
				mtime = scanFile.mtime,
				ctime = scanFile.ctime,

				hash = DEFAULT_HASH
			)
			self.session.add(newData)

		self.session.query(ScanFileData).delete()
		print("committing to db")	

		self.session.commit()
		print("committed")
		pass

	def buildHashes(self):
		print("building file hashes")
		missingHashes = self.session.query(FileData).filter(FileData.hash == '')
		print("Hashes missing: {0}".format(missingHashes.count()))

		fileIndex = 0
		numFiles = missingHashes.count()
		for fileData in missingHashes.all():
			fileIndex += 1
			print("building hash {1}/{2}for: {0}".format(fileData.path, fileIndex, numFiles))
			fileData.hash = getDigest(fileData.path)

		print("committing to session")
		self.session.commit()
		

	def buildDhashes(self):
		print("building dhashes")
		missingDHashes = self.session.query(FileData) \
			.filter(FileData.hash != DEFAULT_HASH) \
			.filter(~ exists().where(FileData.hash == DHashData.hash)) \
			.group_by(FileData.hash)

		print("DHashes missing: {0}".format(missingDHashes.count()))
		dhashSize = 8
		fileIndex = 0
		numFiles = missingDHashes.count()
		with mp.Pool() as pool:
			for curData in pool.imap(
					makeDHashData, ((x, dhashSize) for x in missingDHashes.all())):
				if not curData:
					raise OperationInterruptedException()
				fileIndex += 1
				newData = curData[0]
				path = curData[1]
				if isinstance(newData, Exception):
					print("exception: {0}, file: {1}".format(newData, path))
					continue
				print("building hash {1}/{2}for: {0} : {3}".format(path, fileIndex, numFiles, newData.dhash))
				self.session.add(newData)
			
		print("commiting")
		self.session.commit()

		pass

	def killOcr(self, ocrLang='eng'):
		print("deleting ocr for {0}".format(ocrLang))
		self.session.query(OcrData).filter(OcrData.lang == ocrLang).delete()
		self.session.commit()

	def searchText(self, textPattern, ocrLang='eng', brief: bool = False):
		textQuery = self.session.query(FileData.path, OcrData.text) \
			.filter(OcrData.hash == FileData.hash) \
			.filter(OcrData.lang == ocrLang) \
			.filter(OcrData.text != "") \
			.filter(OcrData.text.ilike(textPattern)) \
			.group_by(OcrData.hash) \
			.order_by(FileData.path)

		if not brief:
			numResults = textQuery.count()
			print("{0} result(s)".format(numResults))

		for cur in textQuery.all():			
			if brief:
				print(cur[0])
			else:
				print("{0}:\n{1}\n".format(cur[0], str(cur[1]).replace('\n', '\\')))

	def buildOcr(self, ocrLang='eng', mask=None):
		pytesseract.pytesseract.tesseract_cmd = self.config.tesscmd

		print("tess languages: {0}".format(pytesseract.get_languages()))
		missingOcr = self.session.query(FileData) \
			.filter(FileData.hash != DEFAULT_HASH) \
			.filter(~ exists().where((FileData.hash == OcrData.hash) & (OcrData.lang == ocrLang))) \
			.group_by(FileData.hash)

		#print(missingOcr)
		if (mask):
			missingOcr = missingOcr.filter(FileData.path.ilike(mask))
			print(missingOcr)
		numFiles = missingOcr.count()
		print("missing translations: {0}".format(numFiles))
		fileIndex = 0

		useFullData = False
		with mp.Pool() as pool:
			fileLimit = 1000
			for data in pool.imap(makeOcrData, 
					(
						((x.path, x.size, x.hash), self.config.tesscmd, ocrLang, useFullData) for x in missingOcr.all()
					)):
				if not data:
					raise OperationInterruptedException()

				err = data[2]
				ocrTuple = data[0]
				fileData: tuple[str, int, str] = data[1]
				filePath = fileData[0]
				fileSize = fileData[1]
				fileHash = fileData[2]

				fileIndex += 1
				print("building ocr {1}/{2}for: {0}".format(filePath, fileIndex, numFiles))
				if isinstance(err, Exception):
					print("exception: {0}: {1}".format(err, filePath))
					continue

				ocrText = ocrTuple[0]
				ocrLang = ocrTuple[1]

				print(str(ocrText).replace('\n', ' \\ '))
				newData = OcrData(
					hash = fileHash,
					size = fileSize,
					lang = ocrLang,
					text = ocrText
				)
				#print(newData)
				self.session.add(newData)
				# if (fileIndex % fileLimit) == 0:
				# 	print("saving due to file limit: {0}".format(fileLimit))
				# 	self.session.commit()
				
		print("commiting")
		self.session.commit()
		pass

	def killPalettes(self):
		print("deleting palettes")
		self.session.query(PaletteData).delete()
		print("comitting")
		self.session.commit()
		print("done")
		pass

	def buildPalettes(self):
		missingPal = self.session.query(FileData) \
			.filter(FileData.hash != DEFAULT_HASH) \
			.filter(~ exists().where(FileData.hash == PaletteData.hash)) \
			.group_by(FileData.hash)

		print(missingPal)

		numFiles = missingPal.count()
		print("missing palettes: {0}".format(numFiles))
		with mp.Pool() as pool:
			fileIndex = 0
			for curData in pool.imap(makePaletteData, missingPal.all(), chunksize = 8):
				if not curData:
				 	raise OperationInterruptedException()
				newData = curData[0]
				filePath = curData[1]
				err = curData[2]
				if err and isinstance(err, KeyboardInterrupt):
				 	raise OperationInterruptedException()
				if err and isinstance(err, Exception):
					print("exception: \"{0}\" in file: \"{1}\"".format(err, filePath))
					continue
				if isinstance(err, OSError):
					print("os error: {0}".format(err))
					continue
				fileIndex += 1
				print("building palette {1}/{2} ({3}) for: {0}".format(filePath, fileIndex, numFiles, newData.palette))
				#print(newData)
				self.session.add(newData)

		self.session.commit()
		pass

	def __init__(self) -> None:
		self.config = Config.getConfig()
		self.engine = create_engine("sqlite:///{0}".format(self.config.dbpath))
		Base.metadata.create_all(self.engine)

		Session = sessionmaker(bind = self.engine)
		self.session: sqlalchemy.orm.Session = Session()

		pass

	def openRandom(self) -> None:
		rec = self.session.query(FileData).order_by(func.random()).first()
		if not rec:
			return
		path = rec.path
		fullPath = Path(path)
		path = fullPath.absolute()
		print(path)
		print("opening {0}".format(path))
		os.startfile(path)
		#subprocess.call(['start', path])
		#os.open(path)

	def colorLike(self, colorQuery: str, brief: bool):
		colors = self.session.query(
			PaletteData.palette, FileData.path
		).join(
			# PaletteData, (FileData.hash == PaletteData.hash) & (FileData.size == PaletteData.size)
			PaletteData, (FileData.hash == PaletteData.hash)
		).filter(PaletteData.palette.ilike(colorQuery)).order_by(PaletteData.palette, FileData.path).distinct()
		
		if not brief:
			numResults = colors.count()
			if not numResults:
				print("nothing found")
				return
			print("found results: {0}".format(numResults))
		prevVal = ""
		for x in colors.all():
			group = x[0]
			path = x[1]
			if (group != prevVal):
				if not brief:
					print("\n{0}:".format(group))
				prevVal = group
			print("{0}".format(path))
		#print(colors.all())

	def findColor(self, col: str, mainColor: bool, brief: bool):
		colorQuery = "{0}%".format(col) if mainColor else "%{0}%".format(col)
		self.colorLike(colorQuery, brief)

	def listColors(self):
		print("listing colors")
		colors = self.session.query(
			PaletteData.palette, FileData.path
		).join(
			# PaletteData, (FileData.hash == PaletteData.hash) & (FileData.size == PaletteData.size)
			PaletteData, (FileData.hash == PaletteData.hash)
		).order_by(PaletteData.palette, FileData.path).distinct()
		
		prevVal = ""
		for x in colors.all():
			group = x[0]
			path = x[1]
			if (group != prevVal):
				print("\n{0}:".format(group))
				prevVal = group
			print("{0}".format(path))
		#print(colors.all())
		pass

	def exportJson(self, filepath):
		with open(filepath, "w", encoding="utf8") as outFile:
			outData = {}
			outData['files'] = [
				(x.path, x.hash, x.size, datetime.timestamp(x.ctime), datetime.timestamp(x.mtime)) for x in self.session.query(FileData).all()
			]
			outData['pal'] = [
				(x.hash, x.size, x.palette) for x in self.session.query(PaletteData).all()
			]
			outData['dhash'] = [
				(x.hash, x.size, x.dhash, x.hashSize) for x in self.session.query(DHashData).all()
			]
			outData['ocr'] = [
				(x.hash, x.size, x.lang, x.text) for x in self.session.query(OcrData).all()
			]
			json.dump(outData, outFile, indent='\t')

	def importJson(self, filepath):
		with open(filepath, "r", encoding="utf8") as inFile:
			inData = json.load(inFile)
			print('adding files')
			for x in inData['files']:
				newData = FileData(
					path = x[0],
					hash = x[1],
					size = x[2],
					ctime = datetime.fromtimestamp(x[3]),
					mtime = datetime.fromtimestamp(x[4])
				)
				self.session.add(newData)
			print('adding palettes')
			for x in inData['pal']:
				newData = PaletteData(
					hash = x[0],
					size = x[1],
					palette = x[2]
				)
				self.session.add(newData)
			print('adding dhash')
			for x in inData['dhash']:
				newData = DHashData(
					hash = x[0],
					size = x[1],
					dhash = x[2],
					hashSize = x[3]
				)
				self.session.add(newData)
			print('adding ocr')
			for x in inData['ocr']:
				newData = OcrData(
					hash = x[0],
					size = x[1],
					lang = x[2],
					text = x[3]
				)
				self.session.add(newData)
			print('comitting')
			self.session.commit()
			print('done')
	
	def findFiles(self, pattern: str, brief: bool = False):
		files = self.session.query(FileData.path) \
			.filter(FileData.path.ilike(pattern)) \
			.order_by(FileData.path)

		if not brief:
			print("{0} results".format(files.count()))

		for x in files.all():
			print(x[0])

	def killDupes(self):
		print("cleaning duplicate palettes")
		distinctPals = self.session.query(PaletteData.id) \
			.group_by(PaletteData.hash)
		killPals = self.session.query(PaletteData) \
			.filter(~PaletteData.id.in_(distinctPals))

		numToKill = killPals.count()
		if (numToKill):
			print("deleting {0} duplicate palettes".format(numToKill))

			for x in killPals.all():
				self.session.delete(x)
		else:
			print("no duplicate palettes")

		print("cleaning duplicate image hashes")
		distinctImHashes = self.session.query(DHashData.id) \
			.group_by(DHashData.hash)
		killImHashes = self.session.query(DHashData) \
			.filter(~DHashData.id.in_(distinctImHashes))

		numToKill = killImHashes.count()
		if (numToKill):
			print("deleting {0} duplicate imHashes".format(numToKill))

			for x in killImHashes.all():
				self.session.delete(x)
				pass
		else:
			print("no duplicate image hashes")

		print("cleaning ocr")
		langList = self.session.query(OcrData.lang) \
			.group_by(OcrData.lang)
		langs = langList.all()
		print("languages: {0}".format(langs))
		for x in langs:
			lang = x[0]
			print("Cleaning: {0}".format(lang))
			distinctOcr = self.session.query(OcrData.id) \
				.filter(OcrData.lang == lang) \
				.group_by(OcrData.hash)
			distinctCount = distinctOcr.count()
			killOcr = self.session.query(OcrData) \
				.filter(OcrData.lang == lang) \
				.filter(~OcrData.id.in_(distinctOcr))
			killCount = killOcr.count()
			print("Disctinct: {0}; kill: {1}".format(distinctCount, killCount))
			if killCount > 0:
				print("Cleaning {0} duplicates".format(killCount))
				for x in killOcr.all():
					self.session.delete(x)
			else:
				print("No duplicates to kill")

		print("comitting")
		self.session.commit()
		print("done")

		pass

	def commitSession(self):
		self.session.commit()

def buildParser():
	parse = argparse.ArgumentParser()
	parse.add_argument("--scan", help="scan filesystem", action="store_true")
	parse.add_argument("--pal", help="build palettes", action="store_true")
	parse.add_argument("--killpal", help="kill palettes", action="store_true")
	parse.add_argument("--killdupes", help="kill duplicate entries", action="store_true")
	parse.add_argument("--hash", help="build file hashes", action="store_true")
	parse.add_argument("--imghash", help="build image hashes", action="store_true")
	parse.add_argument("--ocr", help="ocr images", action="store_true")
	parse.add_argument("--killocr", help="kill ocr images", action="store_true")
	parse.add_argument("--ocrmask", help="ocr file mask for ilike", action="store", default=None)
	parse.add_argument("--lang", help="ocr language", action="store", default='eng')
	parse.add_argument("--random", help="open random image", action="store_true")
	parse.add_argument("--findmaincolor", help="list images with specified main colors. (ROYGBCMKLW)", action="store")
	parse.add_argument("--findcolor", help="list images with specified colors (ROYGBCMKLW)", action="store")
	parse.add_argument("--findfiles", help="list paths matchin pattern (ilike)", action="store")
	parse.add_argument("--colorlike", help="color search using ilike syntax (ROYGBCMKLW)", action="store")
	parse.add_argument("--listcolors", help="list image colors", action="store_true")
	parse.add_argument("--brief", help="print less stuff", action="store_true")
	parse.add_argument("--exportjson", help="export database to file", action="store")
	parse.add_argument("--importjson", help="import database from file", action="store")
	parse.add_argument("--searchtext", help="search text in db. Uses ilike pattern", action="store")
	return parse

def main():
	sys.stdout.reconfigure(encoding='utf-8')
	
	parser = buildParser()
	#parser.print_help()
	args = parser.parse_args()
	#print(args)
	#print(args.scan)
	dbProc = DbProcessor()
	try:
		if (args.scan):
			dbProc.scanFilesystem()
		if (args.killpal):
			dbProc.killPalettes()
		if (args.killocr):
			dbProc.killOcr(args.lang)
		if (args.hash):
			dbProc.buildHashes()
		if (args.imghash):
			dbProc.buildDhashes()
		if (args.ocr):
			dbProc.buildOcr(args.lang, args.ocrmask)
		if (args.pal):
			dbProc.buildPalettes()
		if (args.killdupes):
			dbProc.killDupes()
	except KeyboardInterrupt:
		print("keyboard interrupt on lengthy operation. Saving to db.")
		dbProc.commitSession()		
	except OperationInterruptedException:
		print("operation interrupted on lengthy operation. Saving to db.")
		dbProc.commitSession()

	if (args.findmaincolor):
		dbProc.findColor(args.findmaincolor, True, args.brief)
	if (args.findcolor):
		dbProc.findColor(args.findcolor, False, args.brief)
	if (args.colorlike):
		dbProc.colorLike(args.colorlike, args.brief)
	if (args.listcolors):
		dbProc.listColors()
	if (args.exportjson):
		dbProc.exportJson(args.exportjson)
	if (args.importjson):
		dbProc.importJson(args.importjson)
	if (args.searchtext):
		dbProc.searchText(args.searchtext, args.lang, args.brief)
	if (args.findfiles):
		dbProc.findFiles(args.findfiles, args.brief)

	if (args.random):
		dbProc.openRandom()

if __name__ == "__main__":
	main()