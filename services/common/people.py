"""The people the isekai premise draws: real names and the rest of a life, so fifty arrivals are fifty people.

premise.origin() draws where someone is from, their age, job and household. Left to itself a model then gives
every one of them the same few names (Sarah Chen, Marcus Reyed, Emily Carter), the same personality (warm,
wry, quietly brave) and the same way of coping (determined, hopeful). This module draws those too, from the
guid, so a rerun draws the same person and no two people are the same by default:

  name          a first name that was common in the year they were born, for their gender, and a family name
                from their family's background; a Quebecer is mostly French-Canadian, a Texan more often
                Mexican-American, a Torontonian more often South Asian or Chinese
  personality   the five broad traits, each drawn low, middling or high; only the clear ones are said
  faith, hobby, way of talking, what they miss, what they left unfinished, what they fear
  left_behind   the one person back home they think of most, named and aged to fit
  coping        how they are taking being trapped here
  stance        what they are doing about it (the front line, waiting in town, helping newcomers, trading...)

Background is used for names and nothing else: the prompt tells the model a family name, never what to make
of it. Stdlib only.
"""
import re

BIRTH_YEAR_NOW = 2026

# ---------------------------------------------------------------------------
# first names by birth decade, common in the US and Canada in those years (both lists, mixed on purpose)

FIRST = {
    1940: {
        "f": ["Linda", "Carol", "Sharon", "Judith", "Barbara", "Patricia", "Joan", "Shirley", "Nancy", "Diane",
              "Marilyn", "Joyce", "Beverly", "Gloria", "Janet", "Bonnie", "Darlene", "Frances", "Lorraine", "Gail"],
        "m": ["Gerald", "Ronald", "Larry", "Dennis", "Kenneth", "Donald", "Roger", "Wayne", "Harold", "Ralph",
              "Eugene", "Carl", "Dale", "Leonard", "Norman", "Clifford", "Lloyd", "Howard", "Earl", "Douglas"],
    },
    1950: {
        "f": ["Deborah", "Debra", "Cynthia", "Pamela", "Brenda", "Kathy", "Donna", "Sandra", "Susan", "Karen",
              "Peggy", "Rhonda", "Vicki", "Connie", "Cheryl", "Teresa", "Sheila", "Denise", "Wanda", "Rita"],
        "m": ["Gary", "Jeffrey", "Randy", "Terry", "Bruce", "Keith", "Craig", "Rodney", "Ricky", "Steven",
              "Greg", "Dwayne", "Danny", "Russell", "Phillip", "Alan", "Wesley", "Bobby", "Vernon", "Curtis"],
    },
    1960: {
        "f": ["Lisa", "Kimberly", "Tammy", "Michelle", "Dawn", "Tina", "Lori", "Julie", "Laura", "Kelly",
              "Robin", "Wendy", "Tracy", "Sherry", "Angela", "Renee", "Colleen", "Lynn", "Cathy", "Jill"],
        "m": ["Todd", "Troy", "Darren", "Kevin", "Brian", "Mark", "Scott", "Timothy", "Tony", "Darryl",
              "Glenn", "Kurt", "Brent", "Marty", "Jeff", "Shawn", "Rick", "Doug", "Mitchell", "Barry"],
    },
    1970: {
        "f": ["Jennifer", "Amy", "Heather", "Melissa", "Stephanie", "Nicole", "Christy", "Shannon", "Erin",
              "Misty", "April", "Crystal", "Tara", "Kristen", "Monica", "Holly", "Jody", "Stacey", "Leah", "Becky"],
        "m": ["Jason", "Chad", "Travis", "Shane", "Corey", "Jeremy", "Aaron", "Derek", "Brandon", "Jamie",
              "Nathan", "Dustin", "Ryan", "Marcus", "Trevor", "Joel", "Sean", "Casey", "Brett", "Heath"],
    },
    1980: {
        "f": ["Ashley", "Jessica", "Amanda", "Brittany", "Megan", "Lauren", "Courtney", "Danielle", "Kayla",
              "Tiffany", "Chelsea", "Lindsay", "Whitney", "Natalie", "Vanessa", "Kristina", "Jenna", "Allison",
              "Krystal", "Casey"],
        "m": ["Joshua", "Tyler", "Kyle", "Justin", "Cody", "Zachary", "Dustin", "Adam", "Jordan", "Andrew",
              "Brandon", "Derrick", "Mitchell", "Colin", "Evan", "Garrett", "Seth", "Spencer", "Jared", "Cameron"],
    },
    1990: {
        "f": ["Taylor", "Hannah", "Alexis", "Samantha", "Madison", "Kaitlyn", "Morgan", "Destiny", "Jasmine",
              "Haley", "Shelby", "Sierra", "Paige", "Brianna", "Mackenzie", "Kelsey", "Savannah", "Abby", "Raven",
              "Bethany"],
        "m": ["Austin", "Dylan", "Logan", "Hunter", "Connor", "Caleb", "Devin", "Trent", "Mason", "Jacob",
              "Noah", "Brady", "Colton", "Tanner", "Riley", "Blake", "Isaiah", "Malik", "Parker", "Owen"],
    },
    2000: {
        "f": ["Emma", "Madelyn", "Ava", "Chloe", "Zoe", "Brooklyn", "Aubrey", "Peyton", "Avery", "Kylie",
              "Riley", "Addison", "Gabriella", "Mya", "Jayla", "Makayla", "Sydney", "Leah", "Ella", "Nevaeh"],
        "m": ["Aiden", "Jayden", "Ethan", "Landon", "Brayden", "Gavin", "Carter", "Wyatt", "Liam", "Elijah",
              "Jaxon", "Xavier", "Chase", "Bryce", "Easton", "Kaden", "Micah", "Nolan", "Cole", "Declan"],
    },
}

# ---------------------------------------------------------------------------
# family backgrounds: a family name pool, and sometimes first names of their own
#
# first_share is how often someone of that background has a first name from it rather than from FIRST.

BACKGROUNDS = {
    "anglo": dict(first_share=0.0, family=[
        "Miller", "Johnson", "Smith", "Brown", "Davis", "Wilson", "Taylor", "Anderson", "Thompson", "Moore",
        "Clark", "Lewis", "Walker", "Hall", "Young", "Allen", "Wright", "Scott", "Green", "Baker", "Adams",
        "Nelson", "Hill", "Campbell", "Mitchell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Parker",
        "Collins", "Edwards", "Stewart", "Morris", "Cook", "Rogers", "Morgan", "Cooper", "Peterson", "Bailey",
        "Reed", "Kelly", "Howard", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Wood", "Bennett", "Gray",
        "Hughes", "Price", "Sanders", "Myers", "Long", "Ross", "Foster", "Powell", "Jenkins", "Perry", "Russell",
        "Sullivan", "Bell", "Coleman", "Butler", "Henderson", "Barnes", "Fisher", "Graham", "Hamilton",
        "Wallace", "Cole", "West", "Jordan", "Owens", "Reynolds", "Ellis", "Harrison", "Gibson", "McDonald",
        "Marshall", "Hayes", "Murray", "Ford", "Wells", "Webb", "Palmer", "Dixon", "Hunt", "Hart", "Stone",
        "Holt", "Pratt", "Lowe", "Burke", "Doyle", "Quinn", "Fitzgerald", "O'Brien", "Kennedy", "Murphy",
        "Brennan", "Gallagher", "MacLeod", "Fraser", "Robertson", "Duncan"]),
    "german_dutch_scandinavian": dict(first_share=0.0, family=[
        "Schmidt", "Mueller", "Schneider", "Fischer", "Weber", "Becker", "Hoffman", "Koch", "Bauer", "Richter",
        "Klein", "Wolf", "Schroeder", "Zimmerman", "Krueger", "Hartmann", "Lange", "Schultz", "Vogel", "Brandt",
        "Van Dyke", "De Vries", "Vanderberg", "Hansen", "Larson", "Olson", "Nelson", "Swanson", "Lindquist",
        "Johansson", "Berg", "Halvorsen", "Nygaard", "Erickson", "Lund", "Thorson"]),
    "italian_polish_east_european": dict(first_share=0.0, family=[
        "Russo", "Romano", "Esposito", "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti", "DeLuca",
        "Mancini", "Costa", "Rinaldi", "Lombardi", "Moretti", "Ferraro", "Kowalski", "Nowak", "Wisniewski",
        "Lewandowski", "Zielinski", "Kaminski", "Wojcik", "Kozlowski", "Jankowski", "Mazur", "Kovacs",
        "Novak", "Horvath", "Petrov", "Ivanov", "Kuznetsov", "Melnyk", "Shevchenko", "Bondarenko", "Popescu"]),
    "french_canadian": dict(first_share=0.75, first={
        "f": ["Genevieve", "Isabelle", "Nathalie", "Julie", "Marie-Eve", "Sophie", "Melanie", "Chantal", "Josee",
              "Annie", "Catherine", "Valerie", "Karine", "Sylvie", "Manon", "Lea", "Camille", "Rosalie", "Noemie",
              "Elodie", "Francine", "Monique", "Lise", "Ginette"],
        "m": ["Jean-Francois", "Mathieu", "Sebastien", "Maxime", "Etienne", "Guillaume", "Francis", "Alexandre",
              "Olivier", "Simon", "Patrice", "Yannick", "Benoit", "Denis", "Luc", "Rejean", "Gilles", "Marc-Andre",
              "Felix", "Antoine", "Samuel", "William", "Gabriel", "Raymond"]},
        family=["Tremblay", "Gagnon", "Roy", "Cote", "Bouchard", "Gauthier", "Morin", "Lavoie", "Fortin",
                "Gagne", "Ouellet", "Pelletier", "Belanger", "Levesque", "Bergeron", "Leblanc", "Paquette",
                "Girard", "Simard", "Boucher", "Caron", "Beaulieu", "Cloutier", "Dube", "Poirier", "Fournier",
                "Lapointe", "Leclerc", "Lefebvre", "Poulin", "Theriault", "Robichaud", "Arsenault", "Doucet"]),
    "hispanic": dict(first_share=0.55, first={
        "f": ["Maria", "Guadalupe", "Rosa", "Yesenia", "Marisol", "Alejandra", "Veronica", "Daniela", "Lucia",
              "Ximena", "Esperanza", "Carmen", "Adriana", "Valeria", "Itzel", "Leticia", "Araceli", "Yolanda",
              "Paola", "Gabriela", "Camila", "Natalia", "Dolores", "Beatriz"],
        "m": ["Jose", "Luis", "Juan", "Carlos", "Miguel", "Jesus", "Alejandro", "Javier", "Ricardo", "Eduardo",
              "Fernando", "Hector", "Raul", "Rafael", "Arturo", "Mateo", "Santiago", "Diego", "Ramon", "Ernesto",
              "Julio", "Rogelio", "Emilio", "Andres"]},
        family=["Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Perez", "Sanchez",
                "Ramirez", "Torres", "Flores", "Rivera", "Gomez", "Diaz", "Reyes", "Morales", "Cruz", "Ortiz",
                "Gutierrez", "Chavez", "Ramos", "Ruiz", "Alvarez", "Mendoza", "Vasquez", "Castillo", "Jimenez",
                "Moreno", "Romero", "Herrera", "Medina", "Aguilar", "Vargas", "Guzman", "Salazar", "Delgado",
                "Contreras", "Cervantes", "Ochoa", "Villarreal", "Zamora", "Espinoza", "Trevino", "Benavides"]),
    "black_american": dict(first_share=0.35, first={
        "f": ["Keisha", "Tamika", "Latoya", "Ebony", "Shanice", "Aaliyah", "Imani", "Jada", "Nia", "Tasha",
              "Monique", "Danielle", "Kiara", "Deja", "Tanisha", "Ayanna", "Shante", "Brianna", "Yolanda", "Octavia"],
        "m": ["DeShawn", "Jamal", "Tyrone", "Darnell", "Terrence", "Andre", "Marquis", "Jalen", "DaQuan",
              "Rashad", "Cedric", "Lamar", "Reginald", "Maurice", "Dante", "Khalil", "Devonte", "Isaiah", "Darius",
              "Jerome"]},
        family=["Washington", "Jefferson", "Jackson", "Johnson", "Williams", "Brown", "Jones", "Davis", "Harris",
                "Robinson", "Thomas", "Moore", "Taylor", "White", "Thompson", "Mitchell", "Banks", "Booker",
                "Freeman", "Gaines", "Holmes", "Mosley", "Pettaway", "Simmons", "Battle", "Coleman", "Dorsey",
                "Ellison", "Glover", "Hairston", "Lassiter", "McCray", "Rucker", "Tolbert", "Whitfield", "Wiggins",
                "Toussaint", "Okafor", "Mensah", "Adeyemi", "Asante", "Haile"]),
    "east_asian": dict(first_share=0.3, first={
        "f": ["Mei", "Xiaoling", "Jiyeon", "Yuna", "Hana", "Aiko", "Lin", "Soo-ah", "Yan", "Minji"],
        "m": ["Wei", "Jun", "Hyun-woo", "Kenji", "Hiroshi", "Jae", "Ming", "Takeshi", "Min-jun", "Hao"]},
        family=["Chen", "Wang", "Li", "Zhang", "Liu", "Huang", "Wu", "Zhou", "Lin", "Yang", "Kim", "Lee", "Park",
                "Choi", "Jung", "Kang", "Cho", "Yoon", "Tanaka", "Nakamura", "Yamamoto", "Sato", "Watanabe",
                "Kobayashi", "Ito", "Wong", "Chan", "Leung", "Ho", "Ng", "Lau", "Tsang"]),
    "southeast_asian": dict(first_share=0.3, first={
        "f": ["Linh", "Thao", "Mai", "Ngoc", "Maricel", "Jocelyn", "Rowena", "Analyn"],
        "m": ["Minh", "Duc", "Tuan", "Bao", "Jericho", "Rodel", "Nonoy", "Arnel"]},
        family=["Nguyen", "Tran", "Le", "Pham", "Vu", "Dang", "Bui", "Do", "Santos", "Reyes", "Cruz", "Bautista",
                "Dela Cruz", "Mendoza", "Aquino", "Villanueva", "Castillo", "Pascual", "Manalo", "Soriano"]),
    "south_asian": dict(first_share=0.55, first={
        "f": ["Priya", "Ananya", "Divya", "Harpreet", "Simran", "Neha", "Kavya", "Pooja", "Aisha", "Sana",
              "Manpreet", "Deepa", "Meera", "Ritu"],
        "m": ["Arjun", "Rohan", "Vikram", "Gurpreet", "Harjit", "Sanjay", "Rahul", "Amit", "Imran", "Faisal",
              "Jaspreet", "Nikhil", "Ravi", "Karan"]},
        family=["Patel", "Shah", "Singh", "Sharma", "Gupta", "Kumar", "Mehta", "Desai", "Reddy", "Iyer", "Nair",
                "Gill", "Sandhu", "Dhillon", "Grewal", "Sidhu", "Khan", "Hussain", "Chaudhry", "Malik", "Rahman",
                "Joshi", "Kapoor", "Banerjee"]),
    "middle_eastern": dict(first_share=0.5, first={
        "f": ["Layla", "Nour", "Yasmin", "Rania", "Leila", "Dina", "Mariam", "Shirin"],
        "m": ["Omar", "Karim", "Tarek", "Sami", "Hassan", "Ali", "Ramin", "Ziad"]},
        family=["Haddad", "Khoury", "Nasser", "Saleh", "Mansour", "Hamdan", "Aziz", "Farah", "Karimi", "Hosseini",
                "Rahimi", "Abboud", "Bitar", "Darwish", "Sayegh", "Yousef"]),
    "jewish": dict(first_share=0.15, first={
        "f": ["Rachel", "Miriam", "Shira", "Talia", "Naomi", "Rivka"],
        "m": ["Avi", "Eli", "Noam", "Ari", "Moshe", "Benji"]},
        family=["Cohen", "Levy", "Goldberg", "Friedman", "Shapiro", "Katz", "Rosen", "Weiss", "Klein",
                "Rosenberg", "Silverman", "Abrams", "Feldman", "Horowitz", "Bernstein", "Kaplan", "Greenberg"]),
    "indigenous": dict(first_share=0.0, family=[
        "Begay", "Yazzie", "Benally", "Tsosie", "Nez", "Etsitty", "Cardinal", "Sinclair", "Bear", "Littlechild",
        "Swiftwolf", "Redcloud", "Whitehorse", "Two Bulls", "Eagleheart", "Bighorn", "Morningstar", "Okemaw",
        "Wapass", "Thunderchild", "Manyfingers", "Crowshoe", "Lafromboise", "Delorme"]),
}

# How common each background is, before where someone lives shifts it.
BACKGROUND_WEIGHTS = {
    "anglo": 40, "german_dutch_scandinavian": 9, "italian_polish_east_european": 8, "french_canadian": 1,
    "hispanic": 16, "black_american": 11, "east_asian": 4, "southeast_asian": 3, "south_asian": 3,
    "middle_eastern": 1.5, "jewish": 2, "indigenous": 1.5,
}
# Where someone lives changes the odds: a multiplier on BACKGROUND_WEIGHTS for that home.
REGIONAL = {
    "Quebec": {"french_canadian": 60, "hispanic": 0.2, "black_american": 0.4},
    "New Brunswick": {"french_canadian": 25, "hispanic": 0.1, "black_american": 0.2},
    "Ontario": {"south_asian": 4, "east_asian": 2.5, "hispanic": 0.15, "black_american": 0.5,
                "french_canadian": 4, "southeast_asian": 2, "middle_eastern": 2},
    "British Columbia": {"east_asian": 4, "south_asian": 3.5, "hispanic": 0.1, "black_american": 0.15,
                         "indigenous": 2.5, "southeast_asian": 2},
    "Alberta": {"south_asian": 2, "southeast_asian": 2.5, "hispanic": 0.1, "black_american": 0.3,
                "indigenous": 3, "german_dutch_scandinavian": 1.5},
    "Manitoba": {"indigenous": 6, "hispanic": 0.1, "black_american": 0.2, "southeast_asian": 3,
                 "italian_polish_east_european": 2},
    "Saskatchewan": {"indigenous": 6, "hispanic": 0.1, "black_american": 0.2, "german_dutch_scandinavian": 2},
    "Nova Scotia": {"hispanic": 0.1, "black_american": 0.4, "french_canadian": 4},
    "Newfoundland and Labrador": {"hispanic": 0.05, "black_american": 0.1, "indigenous": 2},
    "Texas": {"hispanic": 2.4}, "California": {"hispanic": 2.4, "east_asian": 3, "southeast_asian": 3},
    "New Mexico": {"hispanic": 3, "indigenous": 6}, "Arizona": {"hispanic": 1.9, "indigenous": 3},
    "Florida": {"hispanic": 1.8}, "Nevada": {"hispanic": 1.8}, "Colorado": {"hispanic": 1.4},
    "New York": {"hispanic": 1.2, "jewish": 4, "east_asian": 2, "black_american": 1.3},
    "New Jersey": {"hispanic": 1.3, "jewish": 2.5, "south_asian": 3},
    "Georgia": {"black_american": 2.8}, "Mississippi": {"black_american": 3.3}, "Louisiana": {"black_american": 2.9},
    "Alabama": {"black_american": 2.4}, "South Carolina": {"black_american": 2.4},
    "Maryland": {"black_american": 2.7}, "North Carolina": {"black_american": 2}, "Virginia": {"black_american": 1.7},
    "Tennessee": {"black_american": 1.4}, "Illinois": {"hispanic": 1.1, "black_american": 1.3,
                                                      "italian_polish_east_european": 2},
    "Michigan": {"black_american": 1.2, "middle_eastern": 3, "italian_polish_east_european": 1.5},
    "Hawaii": {"east_asian": 8, "southeast_asian": 8, "anglo": 0.5, "black_american": 0.2},
    "Minnesota": {"german_dutch_scandinavian": 3, "hispanic": 0.4}, "Wisconsin": {"german_dutch_scandinavian": 3},
    "North Dakota": {"german_dutch_scandinavian": 3, "indigenous": 3, "hispanic": 0.3},
    "South Dakota": {"german_dutch_scandinavian": 2.5, "indigenous": 5, "hispanic": 0.3},
    "Montana": {"indigenous": 4, "hispanic": 0.3}, "Alaska": {"indigenous": 8, "hispanic": 0.5},
    "Oklahoma": {"indigenous": 5}, "Pennsylvania": {"italian_polish_east_european": 1.8},
    "Massachusetts": {"italian_polish_east_european": 1.5, "hispanic": 0.8},
    "Rhode Island": {"italian_polish_east_european": 2}, "Connecticut": {"italian_polish_east_european": 2},
    "Utah": {"hispanic": 0.9, "black_american": 0.15}, "Idaho": {"black_american": 0.1},
    "Maine": {"black_american": 0.1, "hispanic": 0.1, "french_canadian": 5}, "Vermont": {"black_american": 0.1,
                                                                                         "hispanic": 0.1},
    "New Hampshire": {"black_american": 0.1, "hispanic": 0.2, "french_canadian": 3},
    "West Virginia": {"black_american": 0.3, "hispanic": 0.1}, "Wyoming": {"black_american": 0.1},
}
CANADIAN = {"Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba", "Saskatchewan", "Nova Scotia",
            "New Brunswick", "Newfoundland and Labrador"}


def _weighted(rng, pairs):
    items, weights = zip(*pairs)
    return rng.choices(items, weights=weights, k=1)[0]


def background(rng, home):
    shift = REGIONAL.get(home, {})
    canada = home in CANADIAN
    pairs = []
    for name, w in BACKGROUND_WEIGHTS.items():
        w *= shift.get(name, 1.0)
        if canada and name not in shift:
            # Canada outside the provinces named above: few Hispanic or Black American family names.
            w *= {"hispanic": 0.15, "black_american": 0.3}.get(name, 1.0)
        pairs.append((name, w))
    return _weighted(rng, pairs)


def decade(year):
    return max(1940, min(2000, year // 10 * 10))


def first_name(rng, gender, year, bg):
    """A first name for someone of this background born in this year. gender is 'f' or 'm'."""
    b = BACKGROUNDS[bg]
    if b.get("first") and rng.random() < b["first_share"]:
        return rng.choice(b["first"][gender])
    # A neighbouring decade now and then: parents are not all of a year.
    d = decade(year + rng.choice((-6, 0, 0, 0, 5)))
    return rng.choice(FIRST[d][gender])


def family_name(rng, bg):
    return rng.choice(BACKGROUNDS[bg]["family"])


# ---------------------------------------------------------------------------
# the rest of a person

# The five broad traits. Each is drawn low, middling or high; only a clear low or high is said.
TRAITS = [
    ("curious, restless, up for anything new", "a creature of habit who likes what they know"),
    ("organised, a list-maker, does what they say they will", "disorganised, lives day to day, loses things"),
    ("loud, social, talks to strangers", "quiet, private, needs time alone"),
    ("soft-hearted, avoids conflict, trusts people", "blunt, suspicious, ready to argue"),
    ("anxious, a worrier, takes things hard", "steady, hard to rattle"),
]
FAITH = [
    ("not religious", 30), ("raised Christian, doesn't go to church much", 18), ("a churchgoing Protestant", 12),
    ("Catholic, still goes at Christmas and Easter", 10), ("a devout Catholic", 4), ("evangelical, prays daily", 6),
    ("spiritual but not religious", 7), ("an atheist, and says so", 5), ("Jewish, not very observant", 1.5),
    ("an observant Jew", 0.5), ("Muslim, prays when they can", 2), ("Hindu", 1), ("Sikh", 1), ("Buddhist", 1),
    ("Latter-day Saint", 1.5),
]
HOBBIES = [
    "fantasy football", "knitting", "fishing", "deer hunting", "baking bread", "karaoke", "rock climbing",
    "restoring an old truck", "watching true-crime documentaries", "church choir", "woodworking", "running half marathons",
    "gardening", "reading romance novels", "playing bass in a garage band", "birdwatching", "poker nights",
    "pickleball", "crossword puzzles", "cooking from their grandmother's recipes", "hockey in a beer league",
    "watching baseball", "making TikToks", "painting miniatures", "camping", "salsa dancing", "home brewing",
    "thrift shopping", "volunteering at an animal shelter", "chess", "skateboarding", "quilting", "drawing comics",
    "bowling league", "following the NBA", "yoga", "golf", "snowmobiling", "metal detecting", "board games",
    "competitive barbecue", "bass fishing tournaments", "community theatre", "astronomy", "tinkering with computers",
    "collecting vinyl records", "line dancing", "powerlifting", "sewing their own clothes", "watching anime",
    "hiking every trail near home", "playing guitar in church", "soccer", "photography", "fixing up the house",
    "true-crime podcasts", "canning and pickling", "ice fishing", "motorcycles", "trivia nights",
]
SPEECH = [
    "says \"like\" a lot", "swears casually and creatively", "polite and formal, calls people sir and ma'am",
    "jokes when they are scared", "talks fast and interrupts", "uses as few words as they can",
    "quotes movies constantly", "talks like a teacher, explains everything", "uses military slang",
    "thick regional accent and the expressions to go with it", "apologises too much", "asks a lot of questions",
    "talks in sports metaphors", "very online: memes and internet slang", "slow, careful, thinks before speaking",
    "tells long stories that wander", "sarcastic and dry", "warm and chatty, calls people hon or buddy",
    "blunt to the point of rude", "mumbles and trails off", "uses big words a little wrong",
    "mixes in words from their family's other language", "cheerful no matter what", "complains about everything",
    "talks to themselves out loud", "uses customer-service voice when nervous", "uses gamer slang (if they game)",
]
MISSES = [
    "coffee", "their phone", "their dog", "hot showers", "their bed", "air conditioning", "their kids' voices",
    "fast food", "music on demand", "their car", "being able to call their mother", "cigarettes", "their glasses (they don't need them now)",
    "toilet paper", "their medication", "a cold beer", "their cat", "the internet", "their own face in the mirror",
    "their partner's snoring", "pizza", "their routine", "sweet tea", "poutine", "Tim Hortons", "their hands (the old ones)",
    "knowing what day it is", "their church", "Sunday football", "their garden", "texting their best friend",
    "air that doesn't smell like woodsmoke", "a dentist", "painkillers", "privacy",
]
UNFINISHED = [
    "had just quit their job", "was about to propose", "had a court date next week", "hadn't spoken to their brother in years",
    "had left the stove on, they're almost sure", "owed money they couldn't pay", "was two weeks from graduating",
    "had just found out they were going to be a grandparent", "was waiting on test results", "had just moved to a new city",
    "had said something cruel to someone they love that morning", "had finally gotten sober, ninety days",
    "was in the middle of a divorce", "had just bought a house", "had a job interview the next day",
    "had promised to pick their kid up from school", "had just adopted a puppy", "was planning a surprise party",
    "had a big exam coming", "had been about to tell their family a secret", "was caring for a sick parent alone",
    "had just won a little money on a scratch ticket", "had a wedding to go to that weekend",
    "had been meaning to call an old friend back", "had just started chemo", "was training for their first marathon",
    "had a garden full of tomatoes about to ripen", "was being promoted on Monday", "had a fight with their teenager",
    "had a flight booked to see family",
]
FEARS = [
    "dying here and not coming back", "that their family thinks they're dead", "the dark", "heights",
    "being alone", "that this is a coma and they will never wake", "the undead (or being one)", "deep water",
    "that the way home closes", "losing their mind", "spiders, and this world has huge ones", "crowds",
    "that someone they love came through too and is out there alone", "forgetting their old life",
    "that they deserved this", "the natives finding out what they are", "hunger", "that this is hell",
    "getting old here", "that the ones who seem to know this place are keeping something back",
]
# How they are taking it.
COPING = [
    ("sure it's a dream or a coma and they will wake up any minute", 8), ("grieving, crying when no one is looking", 10),
    ("thrilled: it's the adventure they always wanted", 8), ("numb and practical: food, water, shelter, then think", 12),
    ("angry, looking for someone to blame", 8), ("praying a lot, sure there is a reason", 6),
    ("throwing themselves into getting stronger", 10), ("joking about everything so they don't scream", 9),
    ("terrified of dying and avoiding every risk", 9), ("treating it as a puzzle with rules to work out", 8),
    ("drinking at the inn more than they should", 4), ("holding it together for the people around them", 8),
]
# What they are doing about it, now that it's clear no one can leave.
STANCE = [
    ("pushing to the front: getting strong fast, sure the way home is at the end of the road", 14),
    ("staying near the starting town, waiting for rescue that has not come", 14),
    ("helping newcomers: showing the lost ones how to eat, fight and not die", 10),
    ("trading what they can, and selling what they know to whoever pays", 7),
    ("searching for someone from home they think came through too", 9),
    ("keeping to themselves and trusting nobody yet", 10),
    ("stuck with the first group that would have them, for safety", 12),
    ("hunting for answers: talking to natives, reading what they can, asking why", 8),
    ("trying to make a life here, in case there is no way back", 6),
    ("following whoever seems to know what they're doing", 10),
]
# Which households fit which ages: premise.LIVES is drawn from the ones that fit, so nobody is 28 with grown
# children or 70 and living with their parents.
LIVES_BY_AGE = [
    (18, 24, {"lives alone": 14, "lives with their parents": 30, "lives with roommates": 30,
              "has a partner, no kids": 14, "is a single parent": 4, "has a partner and young kids": 4}),
    (25, 34, {"lives alone": 22, "has a partner and young kids": 22, "has a partner, no kids": 22,
              "is a single parent": 9, "lives with roommates": 12, "lives with their parents": 7,
              "is recently divorced": 2}),
    (35, 44, {"lives alone": 18, "has a partner and young kids": 32, "has a partner, no kids": 14,
              "is a single parent": 12, "is recently divorced": 6, "is caring for an elderly parent": 3,
              "has grown kids": 2}),
    (45, 54, {"lives alone": 16, "has a partner and young kids": 10, "has grown kids": 28,
              "has a partner, no kids": 14, "is a single parent": 8, "is recently divorced": 8,
              "is caring for an elderly parent": 8}),
    (55, 64, {"lives alone": 18, "has grown kids": 46, "has a partner, no kids": 12,
              "is recently divorced": 6, "is caring for an elderly parent": 10}),
    (65, 120, {"lives alone": 30, "has grown kids": 58, "has a partner, no kids": 12}),
]


def life_for(rng, age):
    for lo, hi, weights in LIVES_BY_AGE:
        if lo <= age <= hi:
            return _weighted(rng, weights.items())
    return "lives alone"


# The one person back home they think of most, by household: (relation, gender or None for either, how to age
# them). Ages are "rel" (years older (+) or younger (-) than the person) or "abs" (an age range of its own).
LEFT_BEHIND = {
    "lives alone": [("their mother", 0, "rel", 20, 34), ("their best friend", None, "rel", -3, 3),
                    ("their sister", 0, "rel", -8, 8), ("their brother", 1, "rel", -8, 8),
                    ("their dad", 1, "rel", 22, 36), ("their ex", None, "rel", -5, 5)],
    "has a partner and young kids": [("their daughter", 0, "abs", 1, 12), ("their son", 1, "abs", 1, 12),
                                     ("their wife", 0, "rel", -4, 4), ("their husband", 1, "rel", -4, 4)],
    "has a partner, no kids": [("their wife", 0, "rel", -5, 5), ("their husband", 1, "rel", -5, 5),
                               ("their girlfriend", 0, "rel", -6, 4), ("their boyfriend", 1, "rel", -4, 6)],
    "is a single parent": [("their daughter", 0, "abs", 2, 17), ("their son", 1, "abs", 2, 17)],
    "has grown kids": [("their daughter", 0, "kid", 20, 0), ("their son", 1, "kid", 20, 0),
                       ("their granddaughter", 0, "grand", 1, 0), ("their wife", 0, "rel", -4, 4),
                       ("their husband", 1, "rel", -4, 4)],
    "lives with their parents": [("their mother", 0, "rel", 20, 32), ("their dad", 1, "rel", 22, 34),
                                 ("their little brother", 1, "abs", 8, 15)],
    "lives with roommates": [("their best friend and roommate", None, "rel", -3, 3), ("their girlfriend", 0, "rel", -4, 4),
                             ("their boyfriend", 1, "rel", -4, 4), ("their mother", 0, "rel", 20, 32)],
    "is caring for an elderly parent": [("their mother", 0, "rel", 22, 34), ("their father", 1, "rel", 22, 34)],
    "is recently divorced": [("their daughter", 0, "kid", 3, 0), ("their son", 1, "kid", 3, 0),
                             ("their ex", None, "rel", -5, 5)],
}


def _their_age(rng, age, how, a, b):
    if how == "abs":
        return rng.randint(a, b)
    if how == "kid":            # a child of someone this age: born when they were 20 to 40, at least a years old
        return max(a, age - rng.randint(20, 40))
    if how == "grand":          # a grandchild: some fifty years younger, at least one
        return max(a, age - rng.randint(48, 62))
    return min(97, max(1, age + rng.randint(a, b)))


def personality(rng):
    out = []
    for high, low in TRAITS:
        r = rng.random()
        if r < 0.3:
            out.append(low)
        elif r > 0.7:
            out.append(high)
    if not out:
        out.append(TRAITS[rng.randrange(len(TRAITS))][rng.randrange(2)])
    return out


def left_behind(rng, life, age, bg):
    """(relation, name, age): the person back home they think of most."""
    options = LEFT_BEHIND.get(life, LEFT_BEHIND["lives alone"])
    if age >= 70:   # parents of the very old are gone
        options = [o for o in options if o[0] not in ("their mother", "their dad", "their father")] or options
    rel, g, how, a, b = rng.choice(options)
    their_age = _their_age(rng, age, how, a, b)
    if g is None:
        g = rng.randrange(2)
    # Family shares the background; a partner, ex or friend may not.
    family = rel.split()[-1] in ("mother", "dad", "father", "sister", "brother", "daughter", "son", "granddaughter")
    their_bg = bg if family or rng.random() < 0.6 else _weighted(rng, BACKGROUND_WEIGHTS.items())
    return rel, first_name(rng, "m" if g else "f", BIRTH_YEAR_NOW - their_age, their_bg), their_age


def draw(rng, home, age, gender, life):
    """Everything this module adds to premise.origin(). gender: 0 male, 1 female (the body's, which is theirs)."""
    gk = "f" if gender else "m"
    bg = background(rng, home)
    year = BIRTH_YEAR_NOW - age
    first = first_name(rng, gk, year, bg)
    last = family_name(rng, bg)
    rel, who, who_age = left_behind(rng, life, age, bg)
    return dict(
        earth_name=f"{first} {last}",
        background=bg,
        personality=personality(rng),
        faith=_weighted(rng, FAITH),
        hobby=rng.choice(HOBBIES),
        speech=rng.choice(SPEECH),
        misses=rng.choice(MISSES),
        unfinished=re.sub(r"^was ", "were ", rng.choice(UNFINISHED)),   # said after "they"
        fear=rng.choice(FEARS),
        coping=_weighted(rng, COPING),
        stance=_weighted(rng, STANCE),
        left_behind=dict(relation=rel, name=who, age=who_age),
    )
