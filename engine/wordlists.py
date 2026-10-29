"""Built-in word lists for names and filler text (avoids needing extra packages)."""
import numpy as np

FIRST_NAMES = np.array("""
Aaliyah Aaron Abigail Adrian Aiden Alex Alexis Alicia Amara Amir Ana Andre Angela Anika
Avery Bailey Benjamin Bianca Blake Brandon Caleb Camila Carlos Carmen Casey Chen Chloe
Daniel Danielle Deepa Devon Diego Dmitri Elena Eli Elijah Emily Emma Ethan Fatima Felix
Gabriel Grace Hannah Hassan Hiro Imani Isaac Isabella Jada Jamal James Jasmine Javier Jordan
Jose Joseph Julia Kai Kayla Keisha Kenji Kevin Laila Leah Leo Liam Lily Logan Lucas Luis
Maya Mei Mia Michael Mohammed Morgan Nadia Naomi Nathan Nia Noah Olivia Omar Priya Quinn
Rafael Riley Rosa Ryan Samuel Sara Sofia Taylor Thomas Valentina Wei William Yusuf Zara Zoe
""".split())

LAST_NAMES = np.array("""
Adams Ahmed Ali Allen Alvarez Anderson Baker Bell Brooks Brown Campbell Carter Chen Clark
Collins Cruz Davis Diaz Edwards Evans Flores Garcia Gomez Gonzalez Green Gupta Hall Harris
Hernandez Hill Huang Jackson James Johnson Jones Kaur Kim King Kumar Lee Lewis Li Lopez
Martin Martinez Mitchell Moore Morales Morgan Murphy Nguyen Okafor Ortiz Park Parker Patel
Perez Phillips Ramirez Reed Reyes Rivera Roberts Robinson Rodriguez Rogers Sanchez Santos
Scott Shah Singh Smith Stewart Taylor Thomas Thompson Torres Turner Walker Wang Ward Watson
White Williams Wilson Wright Wu Yang Young Zhang
""".split())

FILLER_WORDS = np.array("""
lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut
labore et dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris
nisi aliquip ex ea commodo consequat duis aute irure in reprehenderit voluptate velit esse
cillum fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt culpa qui
officia deserunt mollit anim id est laborum
""".split())
