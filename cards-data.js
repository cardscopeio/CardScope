// Shared card data for CardScope.io
// Used by index.html (browse grid) and card.html (card detail template)
// so both pages read from a single source instead of duplicating card data.

const defaultCards = [
    {
        player: "Mike Trout",
        year: "2011",
        brand: "Topps Chrome",
        type: "Rookie Autograph",
        price: "$8,750",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "One of the most sought-after modern baseball cards, this Mike Trout rookie autograph from 2011 Topps Chrome represents the emergence of baseball's greatest player of his generation. Graded PSA 10, this card is in pristine gem mint condition with perfect centering, sharp corners, and a flawless signature."
    },
    {
        player: "Ronald Acuña Jr.",
        year: "2018",
        brand: "Topps Chrome",
        type: "Rookie Autograph",
        price: "$2,200",
        era: "modern",
        condition: "PSA 9",
        emoji: "⚾",
        description: "Ronald Acuña Jr.'s explosive debut season made this 2018 Topps Chrome rookie autograph an instant classic. Graded PSA 9, this card features the young superstar's on-card signature and showcases his early promise as one of baseball's most dynamic players."
    },
    {
        player: "Derek Jeter",
        year: "1993",
        brand: "SP",
        type: "Rookie Card",
        price: "$1,450",
        era: "modern",
        condition: "PSA 9",
        emoji: "⚾",
        description: "The Captain's flagship rookie card from 1993 SP is one of the most iconic cards of the 1990s. This PSA 9 example captures Derek Jeter at the beginning of his legendary career with the New York Yankees, before his five World Series championships and 3,000+ hits."
    },
    {
        player: "Shohei Ohtani",
        year: "2018",
        brand: "Topps Chrome",
        type: "Rookie Card",
        price: "$5,500",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "A true unicorn in baseball history, Shohei Ohtani's 2018 Topps Chrome rookie card in PSA 10 represents the only player to excel as both an elite pitcher and power hitter in the modern era. This gem mint card has become one of the most valuable modern rookies."
    },
    {
        player: "Mickey Mantle",
        year: "1952",
        brand: "Topps",
        type: "Rookie Card",
        price: "$85,000",
        era: "vintage",
        condition: "PSA 5",
        emoji: "⚾",
        description: "The holy grail of baseball cards. Mickey Mantle's 1952 Topps rookie is the most iconic card in the hobby, featuring the Yankees legend in his second year. Even in PSA 5 condition, this card commands massive premiums due to its legendary status and the difficulty of finding centered examples."
    },
    {
        player: "Jackie Robinson",
        year: "1948",
        brand: "Leaf",
        type: "Rookie Card",
        price: "$45,000",
        era: "vintage",
        condition: "PSA 4",
        emoji: "⚾",
        description: "More than just a baseball card, this 1948 Leaf Jackie Robinson rookie represents a pivotal moment in American history. Robinson broke baseball's color barrier in 1947, and this card from his second season is one of the most historically significant cards in the hobby."
    },
    {
        player: "Ken Griffey Jr.",
        year: "1989",
        brand: "Upper Deck",
        type: "Rookie Card",
        price: "$3,200",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "The most iconic card of the junk wax era, Ken Griffey Jr.'s 1989 Upper Deck #1 rookie card in PSA 10 remains highly desirable. Junior's sweet swing and infectious smile made him baseball's most marketable player of the 1990s, and this card launched Upper Deck as a premium brand."
    },
    {
        player: "Willie Mays",
        year: "1952",
        brand: "Topps",
        type: "Rookie Card",
        price: "$28,500",
        era: "vintage",
        condition: "PSA 6",
        emoji: "⚾",
        description: "The Say Hey Kid's 1952 Topps rookie card is one of the most important vintage cards in existence. Willie Mays is widely considered one of the five greatest players ever, and this PSA 6 example from the legendary 1952 Topps set is a museum-quality piece of baseball history."
    },
    {
        player: "Vladimir Guerrero Jr.",
        year: "2019",
        brand: "Topps Chrome",
        type: "Rookie Autograph",
        price: "$1,850",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "Following in his Hall of Fame father's footsteps, Vladimir Guerrero Jr.'s 2019 Topps Chrome rookie autograph in PSA 10 captures one of baseball's most exciting young sluggers. His powerful swing and consistent production make this a strong modern investment piece."
    },
    {
        player: "Roberto Clemente",
        year: "1955",
        brand: "Topps",
        type: "Rookie Card",
        price: "$18,500",
        era: "vintage",
        condition: "PSA 5",
        emoji: "⚾",
        description: "Roberto Clemente's 1955 Topps rookie card honors one of baseball's most beloved humanitarian players. The Hall of Famer's tragic death while delivering earthquake relief supplies has made his cards even more meaningful to collectors. This PSA 5 is a cherished piece of baseball heritage."
    },
    {
        player: "Fernando Tatis Jr.",
        year: "2019",
        brand: "Topps Chrome",
        type: "Rookie Autograph",
        price: "$1,200",
        era: "modern",
        condition: "PSA 9",
        emoji: "⚾",
        description: "Before controversy, Fernando Tatis Jr. burst onto the scene as one of baseball's most electrifying talents. This 2019 Topps Chrome rookie autograph in PSA 9 captures his tremendous potential and remains a polarizing but intriguing piece in the modern market."
    },
    {
        player: "Hank Aaron",
        year: "1954",
        brand: "Topps",
        type: "Rookie Card",
        price: "$32,000",
        era: "vintage",
        condition: "PSA 6",
        emoji: "⚾",
        description: "Hammerin' Hank's 1954 Topps rookie card is a cornerstone of any serious vintage collection. Aaron's 755 home runs stood as the all-time record for decades, and his dignified pursuit of excellence on and off the field makes this PSA 6 rookie a prized possession."
    },
    {
        player: "Bryce Harper",
        year: "2012",
        brand: "Bowman Chrome",
        type: "Prospect Autograph",
        price: "$2,400",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "The most hyped prospect since LeBron James, Bryce Harper's 2012 Bowman Chrome prospect autograph in PSA 10 captures the phenom before his MLB debut. His 2015 MVP season and consistent star power have kept this card relevant in the modern market."
    },
    {
        player: "Sandy Koufax",
        year: "1955",
        brand: "Topps",
        type: "Rookie Card",
        price: "$24,000",
        era: "vintage",
        condition: "PSA 5",
        emoji: "⚾",
        description: "Sandy Koufax's 1955 Topps rookie card represents one of the greatest pitchers who ever lived. His dominant stretch from 1963-1966 included three Cy Young awards and four no-hitters. This PSA 5 rookie is a blue-chip investment in baseball history."
    },
    {
        player: "Juan Soto",
        year: "2018",
        brand: "Topps Chrome",
        type: "Rookie Autograph",
        price: "$1,950",
        era: "modern",
        condition: "PSA 10",
        emoji: "⚾",
        description: "Juan Soto's advanced hitting approach and patient eye at the plate made him an instant star. This 2018 Topps Chrome rookie autograph in PSA 10 gem mint condition captures one of the game's most disciplined young hitters and a perennial MVP candidate."
    },
    {
        player: "Pete Rose",
        year: "1963",
        brand: "Topps",
        type: "Rookie Card",
        price: "$8,500",
        era: "vintage",
        condition: "PSA 7",
        emoji: "⚾",
        description: "Charlie Hustle's 1963 Topps rookie card remains popular despite his controversial ban from baseball. Pete Rose's 4,256 career hits still stand as the all-time record, and this PSA 7 rookie card from the classic 1963 set is a snapshot of baseball's Hit King."
    }
];

// Load user-submitted cards from localStorage (added via sell-cards.html)
function loadUserCards() {
    const stored = localStorage.getItem('userCards');
    return stored ? JSON.parse(stored) : [];
}

// Merge user-submitted cards (first, so they show as newest) with default demo cards
function getAllCards() {
    return [...loadUserCards(), ...defaultCards];
}

// Consistent slug used to link from the browse grid to a card's detail page:
// card.html?card=<slug>
function cardSlug(card) {
    return card.player.toLowerCase().replace(/[.\s]/g, '-');
}
