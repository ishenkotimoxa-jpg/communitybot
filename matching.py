from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import log, prod
from typing import Any


RESULT_COUNT = 3
AXIS_BUDGETS: dict[str, float] = {
    "domain": 26,
    "anchor": 28,
    "role": 12,
    "audience": 10,
    "format": 9,
    "values": 7,
    "environment": 8,
}


@dataclass(frozen=True)
class Evidence:
    axis: str
    value: str
    strength: float


@dataclass(frozen=True)
class AnswerRule:
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class OrganizationProfile:
    facets: Mapping[str, Mapping[str, float]]
    family: str | None = None

    def affinity(self, axis: str, value: str) -> float:
        return self.facets.get(axis, {}).get(value, 0.0)

    # Kept for compatibility with diagnostics written for the previous model.
    @property
    def primary(self) -> frozenset[str]:
        return frozenset(
            value
            for values in self.facets.values()
            for value, affinity in values.items()
            if affinity >= 0.8
        )

    @property
    def secondary(self) -> frozenset[str]:
        return frozenset(
            value
            for values in self.facets.values()
            for value, affinity in values.items()
            if affinity < 0.8
        )

    def strength(self, signal: str) -> float:
        return max(
            (
                affinity
                for values in self.facets.values()
                for value, affinity in values.items()
                if value == signal
            ),
            default=0.0,
        )


@dataclass(frozen=True)
class MatchResult:
    organization_id: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    organization_id: str
    diversity_group: str
    family: str | None
    score: float
    anchor_support: float
    strong_matches: int
    positive_matches: int
    tie_break: int
    reasons: tuple[str, ...]


def _parse_values(specification: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for token in specification.split():
        value, separator, raw_affinity = token.partition("=")
        affinity = float(raw_affinity) if separator else 1.0
        values[value] = affinity
    return values


def _answer(
    *,
    negative: Mapping[str, str] | None = None,
    **facets: str,
) -> AnswerRule:
    evidence: list[Evidence] = []
    for axis, specification in facets.items():
        evidence.extend(
            Evidence(axis=axis, value=value, strength=affinity)
            for value, affinity in _parse_values(specification).items()
        )
    for axis, specification in (negative or {}).items():
        evidence.extend(
            Evidence(axis=axis, value=value, strength=-affinity)
            for value, affinity in _parse_values(specification).items()
        )
    return AnswerRule(tuple(evidence))


def _profile(
    *,
    family: str | None = None,
    **facets: str,
) -> OrganizationProfile:
    return OrganizationProfile(
        facets={
            axis: _parse_values(specification)
            for axis, specification in facets.items()
        },
        family=family,
    )


ANSWER_RULES: dict[str, dict[str, AnswerRule]] = {
    "first_invite": {
        "build": _answer(
            role="creator=.65 organizer=.35",
            values="initiative=.65",
            format="project=.55",
        ),
        "help_new": _answer(
            domain="social=.6",
            role="mentor=.8",
            audience="freshmen=.75",
            values="service=.65",
        ),
        "game": _answer(
            domain="competition=.6 gaming=.45",
            format="tournament=.7",
            values="competition=.7",
        ),
        "topic": _answer(
            domain="knowledge=.7",
            role="analyst=.65",
            format="club=.45",
        ),
        "campus_story": _answer(
            domain="media=.8",
            anchor="university_story=.75",
            role="storyteller=.75",
        ),
        "summer_trip": _answer(
            domain="student_squad=.8",
            environment="summer=.95 travel=.75",
        ),
        "look_all": _answer(values="exploration=.8 beginner=.45"),
    },
    "creative_material": {
        "voice": _answer(
            domain="music=.95", anchor="vocal=.8", role="performer=.55"
        ),
        "instrument": _answer(
            domain="music=.95", anchor="instrumental=.85", role="performer=.5"
        ),
        "dance": _answer(
            domain="dance=.95",
            anchor="dance_practice=.75",
            role="performer=.6",
            environment="physical=.55",
        ),
        "character": _answer(
            domain="theatre=.95", anchor="acting=.8", role="performer=.65"
        ),
        "visual": _answer(
            domain="visual_art=.95", anchor="visual_art_practice=.95", role="creator=.7"
        ),
        "text": _answer(
            domain="literature=.9", anchor="poetry=.8", role="creator=.65"
        ),
        "mix": _answer(
            domain="multidisciplinary_art=.95",
            anchor="mixed_arts=.95",
            role="creator=.7",
            values="exploration=.7",
        ),
        "none": _answer(
            negative={
                "domain": (
                    "music dance theatre visual_art multidisciplinary_art performing_arts"
                ),
                "anchor": "poetry",
                "role": "performer=.65",
            }
        ),
    },
    "best_aftertaste": {
        "helped": _answer(domain="social=.45", values="service=.9 impact=.65"),
        "beautiful": _answer(role="creator=.45", values="aesthetics=.9"),
        "victory": _answer(
            domain="competition=.55", format="tournament=.65", values="competition=.95"
        ),
        "understood": _answer(
            domain="knowledge=.65", role="analyst=.8", values="learning=.75"
        ),
        "own_people": _answer(
            values="community=.9", environment="small_team=.55 team=.45"
        ),
        "big_thing": _answer(
            role="organizer=.65", format="large_project=.75", values="impact=.7"
        ),
        "different": _answer(values="exploration=.85"),
    },
    "ten_minutes": {
        "organize": _answer(role="organizer=.95", values="initiative=.55"),
        "announce": _answer(role="speaker=.95", environment="public=.7"),
        "camera": _answer(
            domain="media=.55",
            anchor="photo_video=.75",
            role="storyteller=.8",
        ),
        "troubleshoot": _answer(role="analyst=.85", values="precision=.7"),
        "support": _answer(role="mentor=.8 helper=.75", values="service=.6"),
        "decorate": _answer(role="creator=.8", values="aesthetics=.75"),
        "any": _answer(values="flexibility=.8 community=.35"),
    },
    "new_team": {
        "connect": _answer(role="facilitator=.9", values="community=.7"),
        "one_two": _answer(environment="small_team=.95", values="community=.45"),
        "newcomers": _answer(
            role="mentor=.95", audience="freshmen=.85", values="service=.55"
        ),
        "represent": _answer(role="representative=.95", values="responsibility=.6"),
        "backstage": _answer(environment="backstage=.95", role="organizer=.35"),
        "alone": _answer(environment="individual=.95"),
        "depends": _answer(values="flexibility=.55"),
    },
    "spring_growth": {
        "speak": _answer(role="speaker=.95", environment="public=.45"),
        "photo_video": _answer(
            domain="media=.75", anchor="photo_video=.9", role="storyteller=.75"
        ),
        "lead": _answer(role="organizer=.95", values="initiative=.65"),
        "people": _answer(
            domain="psychology=.8",
            anchor="psychology_discussion=.65",
            role="analyst=.45 facilitator=.4",
        ),
        "hands": _answer(role="craft=.9", environment="physical=.85"),
        "move": _answer(role="performer=.55", environment="physical=.8 public=.25"),
        "research": _answer(
            domain="science=.85",
            anchor="science_communication=.7",
            role="researcher=.9 analyst=.55",
        ),
        "all": _answer(values="exploration=.9 beginner=.55"),
    },
    "campus_change": {
        "freshmen": _answer(
            domain="social=.65",
            anchor="freshman_adaptation=.85",
            audience="freshmen=.95",
        ),
        "dorm": _answer(
            domain="governance=.75",
            anchor="dorm_advocacy=.95",
            audience="dorm_residents=.95",
        ),
        "studies": _answer(
            domain="governance=.75",
            anchor="education_process=.95",
            audience="academic_groups=.9",
        ),
        "awareness": _answer(
            domain="media=.75", anchor="university_story=.7", audience="students=.55"
        ),
        "movement": _answer(
            domain="sport=.8", anchor="sports_life=.85", audience="students=.55"
        ),
        "introductions": _answer(
            domain="international=.45 social=.35",
            anchor="intercultural_exchange=.5",
            role="facilitator=.7",
        ),
        "create": _answer(role="creator=.7", values="initiative=.7"),
    },
    "event_meaning": {
        "memory": _answer(
            domain="civic_history=1",
            anchor="commemorative_action=1",
            format="public_action=.85 large_event=.45",
            values="memory=.95 tradition=.55",
        ),
        "ball": _answer(
            domain="dance=.85",
            anchor="themed_ball=1",
            format="large_event=.9 performance=.45",
            values="aesthetics=.9 tradition=.85",
        ),
        "sport": _answer(
            domain="sport=.95",
            anchor="sports_event=.95",
            format="tournament=.8 large_event=.65",
        ),
        "cultures": _answer(
            domain="international=.95",
            anchor="multicultural_event=1",
            format="large_event=.75",
        ),
        "charity": _answer(
            domain="social=.85",
            anchor="volunteer_action=.95",
            format="public_action=.75",
            values="service=.9",
        ),
        "science": _answer(
            domain="science=.95",
            anchor="science_conference=1",
            format="conference=.95 large_event=.45",
        ),
        "festival": _answer(
            domain="performing_arts=.8",
            anchor="stage_production=.9",
            format="performance=.9 large_event=.75",
        ),
        "none": _answer(
            negative={"format": "large_event public_action=.7", "role": "organizer=.45"}
        ),
    },
    "rhythm": {
        "weekly": _answer(
            format="rehearsal=.65 training=.45 club=.25",
            environment="regular=.95",
        ),
        "tournaments": _answer(
            format="training=.85 tournament=.75", environment="competitive=.9"
        ),
        "sprints": _answer(format="project=.75", environment="project_based=.95"),
        "summer": _answer(environment="summer=1 travel=.45"),
        "calm": _answer(format="club=.55", environment="calm=.95 small_team=.55"),
        "flexible": _answer(format="short_action=.5", environment="flexible=.95"),
        "no_commitment": _answer(
            values="beginner=.45", environment="low_commitment=.95 flexible=.45"
        ),
    },
    "starting_point": {
        "beginner": _answer(values="beginner=.95 learning=.5"),
        "continue": _answer(values="experience=.9"),
        "adjacent": _answer(values="exploration=.75 experience=.4"),
        "strong_team": _answer(values="community=.65", environment="team=.75"),
        "observe": _answer(values="beginner=.5", environment="low_commitment=.9"),
    },
    "music_format": {
        "solo": _answer(domain="music=1", anchor="vocal_studio=1 solo_vocal=.95"),
        "chamber": _answer(domain="music=1", anchor="mixed_chamber_choir=1"),
        "male_academic": _answer(domain="music=1", anchor="male_academic_choir=1"),
        "piano": _answer(domain="music=1", anchor="piano=1"),
        "orchestra": _answer(domain="music=1", anchor="orchestra=1 instrumental=.65"),
        "band": _answer(domain="music=1", anchor="original_music=1 instrumental=.55"),
        "none": _answer(negative={"domain": "music", "anchor": "vocal instrumental=.8"}),
    },
    "stage_format": {
        "ballroom": _answer(domain="dance=1", anchor="ballroom_training=1"),
        "hiphop": _answer(
            domain="dance=1 competition=.55", anchor="hiphop=1 dance_competition=.7"
        ),
        "contemporary": _answer(
            domain="dance=1 competition=.45",
            anchor="contemporary_dance=1 dance_competition=.65",
        ),
        "ball": _answer(domain="dance=.9", anchor="themed_ball=1"),
        "comedy": _answer(domain="theatre=1", anchor="comedy_improv=1"),
        "mixed": _answer(domain="multidisciplinary_art=1", anchor="mixed_arts=1"),
        "none": _answer(
            negative={"domain": "dance theatre multidisciplinary_art", "role": "performer=.7"}
        ),
    },
    "small_club": {
        "debates": _answer(
            domain="debate=1 knowledge=.45", anchor="structured_debate=1"
        ),
        "books": _answer(domain="literature=1", anchor="book_discussion=1"),
        "games": _answer(domain="gaming=1", anchor="tabletop_games=1"),
        "psychology": _answer(
            domain="psychology=1", anchor="psychology_discussion=1"
        ),
        "history": _answer(
            domain="civic_history=.85 gaming=.4", anchor="reenactment=1"
        ),
        "languages": _answer(
            domain="international=.8 knowledge=.45", anchor="german_language=1"
        ),
        "poetry": _answer(domain="literature=1", anchor="poetry=1"),
        "none": _answer(negative={"format": "club=.9", "environment": "small_team=.55"}),
    },
    "competition_format": {
        "varsity": _answer(
            domain="sport=1 competition=.8", anchor="varsity_support=.9", role="participant=.8"
        ),
        "sport_event": _answer(
            domain="sport=1", anchor="sports_event=1", role="organizer=.9"
        ),
        "esport_player": _answer(
            domain="gaming=1 competition=.8", anchor="esports=1", role="participant=.85"
        ),
        "esport_event": _answer(
            domain="gaming=1 competition=.75", anchor="esports=1", role="organizer=.9"
        ),
        "dance": _answer(
            domain="dance=1 competition=.8", anchor="dance_competition=1", role="performer=.8"
        ),
        "debates": _answer(
            domain="debate=1 competition=.75", anchor="structured_debate=1", role="speaker=.8"
        ),
        "tabletop": _answer(
            domain="gaming=1 competition=.65", anchor="tabletop_games=1"
        ),
        "none": _answer(
            negative={"domain": "competition=.9", "format": "tournament=1", "values": "competition=1"}
        ),
    },
    "impact_target": {
        "freshmen": _answer(
            domain="social=.9", anchor="freshman_adaptation=1", audience="freshmen=1"
        ),
        "dorm": _answer(
            domain="governance=.9", anchor="dorm_advocacy=1", audience="dorm_residents=1"
        ),
        "academic": _answer(
            domain="governance=.9", anchor="education_process=1", audience="academic_groups=1"
        ),
        "good_action": _answer(
            domain="social=1", anchor="volunteer_action=1", values="service=.8"
        ),
        "ecology": _answer(domain="ecology=1 social=.55", anchor="eco_action=1"),
        "memory": _answer(
            domain="civic_history=1", anchor="commemorative_action=1", values="memory=.9"
        ),
        "international": _answer(
            domain="international=.9 social=.55",
            anchor="international_inclusion=1",
            audience="international_students=1",
        ),
        "none": _answer(
            negative={"domain": "social governance ecology civic_history international"}
        ),
    },
    "impact_method": {
        "nearby": _answer(
            role="mentor=.95 helper=.85", format="long_support=.75", values="service=.65"
        ),
        "negotiate": _answer(
            anchor="advocacy_process=.8", role="representative=.95", format="governance=.75"
        ),
        "action": _answer(
            role="organizer=.8 helper=.45", format="short_action=.95 public_action=.55"
        ),
        "rules": _answer(role="representative=.8 organizer=.6", format="governance=.95"),
        "tell": _answer(role="storyteller=.9", format="outreach=.9"),
        "meeting": _answer(role="organizer=.95", format="large_event=.9"),
        "none": _answer(negative={"role": "organizer=.9 representative=.6"}),
    },
    "international_format": {
        "one_culture": _answer(domain="international=1", anchor="german_culture=1"),
        "many_cultures": _answer(
            domain="international=1", anchor="intercultural_exchange=1"
        ),
        "help_guests": _answer(
            domain="international=.9",
            anchor="international_inclusion=1",
            role="mentor=.8",
            audience="international_students=.9",
        ),
        "language": _answer(domain="international=.9", anchor="german_language=1"),
        "event": _answer(
            domain="international=1", anchor="multicultural_event=1", role="organizer=.75"
        ),
        "none": _answer(negative={"domain": "international"}),
    },
    "summer_offer": {
        "children": _answer(domain="student_squad=1 social=.45", anchor="camp_counselor=1"),
        "construction": _answer(domain="student_squad=1", anchor="construction_work=1"),
        "train": _answer(domain="student_squad=1", anchor="train_conductor=1"),
        "restoration": _answer(
            domain="student_squad=1 civic_history=.55", anchor="heritage_restoration=1"
        ),
        "fishery": _answer(domain="student_squad=1", anchor="fishery_far_east=1"),
        "none": _answer(negative={"domain": "student_squad"}),
    },
    "construction_character": {
        "large_object": _answer(anchor="construction_large_object=1 construction_work=.5"),
        "trip": _answer(
            anchor="construction_team_travel=1 construction_work=.5",
            environment="travel=.65 team=.55",
        ),
        "creative": _answer(
            anchor="construction_creative_life=1 construction_work=.5", values="aesthetics=.45"
        ),
        "sport": _answer(
            anchor="construction_sport_life=1 construction_work=.5", values="competition=.55"
        ),
        "team": _answer(anchor="construction_work=.7", values="community=.85"),
        "none": _answer(negative={"anchor": "construction_work"}),
    },
    "science_or_story": {
        "research": _answer(domain="science=1", anchor="original_research=1", role="researcher=.9"),
        "explain": _answer(
            domain="science=.9", anchor="science_communication=1", role="storyteller=.55"
        ),
        "video": _answer(
            domain="media=1", anchor="photo_video=1 university_story=.55", role="storyteller=.8"
        ),
        "person": _answer(
            domain="media=1", anchor="editorial_story=1 university_story=.55", role="storyteller=.85"
        ),
        "lecture": _answer(
            domain="science=.85", anchor="science_conference=.9", role="organizer=.65 speaker=.45"
        ),
        "visual": _answer(
            domain="media=.85 visual_art=.45", anchor="visual_story=1", role="creator=.7"
        ),
        "none": _answer(negative={"domain": "science media"}),
    },
}


ORGANIZATION_PROFILES: dict[str, OrganizationProfile] = {
    "sno": _profile(
        domain="science knowledge=.7",
        anchor="original_research science_communication science_conference",
        role="researcher analyst organizer=.55 speaker=.5",
        audience="students=.7 campus_public=.5",
        format="project conference",
        values="learning initiative=.5 precision=.45",
        environment="project_based public=.45",
    ),
    "oso_press": _profile(
        domain="media",
        anchor="university_story photo_video editorial_story visual_story",
        role="storyteller creator=.6 organizer=.45",
        audience="students campus_public",
        format="outreach project event_coverage=1",
        values="initiative=.55 precision=.55",
        environment="project_based backstage=.75 public=.45 flexible=.45",
    ),
    "curators": _profile(
        domain="social",
        anchor="freshman_adaptation",
        role="mentor facilitator organizer=.55 helper=.75",
        audience="freshmen",
        format="long_support meetings=1",
        values="service community responsibility",
        environment="regular team",
    ),
    "reactor": _profile(
        domain="sport",
        anchor="sports_life sports_event varsity_support",
        role="organizer storyteller=.55 facilitator=.55",
        audience="students campus_public=.7",
        format="tournament large_event=.65 outreach=.45",
        values="competition community initiative",
        environment="project_based public=.65 team=.6 competitive=.6",
    ),
    "dorm_council": _profile(
        domain="governance social=.55",
        anchor="dorm_advocacy advocacy_process",
        role="representative organizer=.7 helper=.65",
        audience="dorm_residents",
        format="governance meetings=1",
        values="service responsibility community",
        environment="regular team=.6",
    ),
    "esta": _profile(
        domain="dance",
        anchor="ballroom_training dance_practice=.65",
        role="performer",
        audience="campus_public=.7",
        format="rehearsal performance training=.75",
        values="aesthetics community beginner=.7 learning=.6",
        environment="regular public physical=.65 team=.7",
    ),
    "volunteer_center": _profile(
        domain="social",
        anchor="volunteer_action",
        role="helper organizer=.65 facilitator=.4",
        audience="people=1 students=.45",
        format="short_action public_action=.7",
        values="service flexibility community=.55",
        environment="flexible project_based=.55 team=.55",
    ),
    "quanto": _profile(
        domain="music",
        anchor="vocal_studio solo_vocal vocal=.7",
        role="performer",
        audience="campus_public=.7",
        format="rehearsal performance",
        values="aesthetics beginner=.75 community=.65",
        environment="regular public team=.55",
    ),
    "vto": _profile(
        domain="theatre performing_arts=.75",
        anchor="comedy_improv acting stage_production=.65",
        role="performer creator speaker=.45",
        audience="campus_public=.8",
        format="rehearsal performance",
        values="initiative community=.6 aesthetics=.5",
        environment="regular public team=.7",
    ),
    "izo": _profile(
        domain="visual_art",
        anchor="visual_art_practice",
        role="creator",
        audience="students=.35",
        format="club workshop=1",
        values="aesthetics learning beginner=.75",
        environment="calm individual=.8 small_team=.55 regular=.5",
    ),
    "cyber_reactor": _profile(
        domain="gaming competition=.8",
        anchor="esports",
        role="participant organizer=.65 analyst=.55",
        audience="students=.55",
        format="tournament training",
        values="competition community=.65 experience=.55",
        environment="competitive team regular=.65",
    ),
    "carpe_diem": _profile(
        family="choir",
        domain="music",
        anchor="mixed_chamber_choir vocal=.55",
        role="performer",
        audience="campus_public=.75",
        format="rehearsal performance",
        values="aesthetics community learning=.6",
        environment="regular public team",
    ),
    "virm": _profile(
        domain="civic_history gaming=.55 competition=.45",
        anchor="reenactment",
        role="participant craft analyst=.45",
        audience="students=.35",
        format="club tournament=.55 field_activity=1",
        values="learning tradition community=.55",
        environment="physical small_team competitive=.45",
    ),
    "poetry_club": _profile(
        domain="literature",
        anchor="poetry",
        role="creator speaker=.65",
        audience="students=.45",
        format="club performance=.55",
        values="aesthetics learning community=.6",
        environment="small_team calm public=.35",
    ),
    "vernost": _profile(
        domain="civic_history social=.55",
        anchor="commemorative_action",
        role="organizer helper=.55 speaker=.35",
        audience="campus_public students=.55",
        format="public_action large_event=.55",
        values="memory service=.65 tradition=.8 impact=.7",
        environment="project_based public=.65 team=.55",
    ),
    "altavista": _profile(
        domain="student_squad social=.55",
        anchor="camp_counselor",
        role="mentor organizer helper=.7",
        audience="children=1",
        format="long_support summer_work=1",
        values="service responsibility community",
        environment="summer travel team physical=.45",
    ),
    "mayak": _profile(
        family="construction_squad",
        domain="student_squad",
        anchor="construction_work construction_large_object",
        role="craft",
        format="summer_work=1",
        values="community responsibility",
        environment="summer travel physical team",
    ),
    "sleipnir": _profile(
        family="construction_squad",
        domain="student_squad",
        anchor="construction_work construction_team_travel",
        role="craft",
        format="summer_work=1",
        values="community responsibility",
        environment="summer travel physical team",
    ),
    "energy_creators": _profile(
        family="construction_squad",
        domain="student_squad",
        anchor="construction_work construction_creative_life",
        role="craft creator=.4",
        format="summer_work=1",
        values="community responsibility aesthetics=.4",
        environment="summer travel physical team",
    ),
    "triumph": _profile(
        family="construction_squad",
        domain="student_squad competition=.35",
        anchor="construction_work construction_sport_life",
        role="craft",
        format="summer_work=1 tournament=.35",
        values="community responsibility competition=.65",
        environment="summer travel physical team competitive=.45",
    ),
    "starostat": _profile(
        domain="governance",
        anchor="education_process advocacy_process=.75",
        role="representative organizer helper=.55",
        audience="academic_groups",
        format="governance meetings=.75",
        values="responsibility service=.55 initiative=.65",
        environment="regular public=.45 team=.55",
    ),
    "explosion": _profile(
        family="competitive_dance",
        domain="dance competition=.75",
        anchor="hiphop dance_competition dance_practice=.55",
        role="performer",
        audience="campus_public=.65",
        format="rehearsal tournament performance",
        values="competition community=.65 aesthetics=.45",
        environment="physical regular public team competitive",
    ),
    "ecomephi": _profile(
        domain="ecology social=.65",
        anchor="eco_action",
        role="organizer helper storyteller=.65",
        audience="students campus_public=.55",
        format="short_action outreach public_action=.65",
        values="service impact community=.55",
        environment="flexible project_based=.65 team=.55",
    ),
    "paradox": _profile(
        family="competitive_dance",
        domain="dance competition=.65",
        anchor="contemporary_dance dance_competition dance_practice=.55",
        role="performer",
        audience="campus_public=.65",
        format="rehearsal tournament=.75 performance",
        values="competition=.8 community=.65 aesthetics=.65",
        environment="physical regular public team competitive=.8",
    ),
    "male_choir": _profile(
        family="choir",
        domain="music",
        anchor="male_academic_choir vocal=.55",
        role="performer",
        audience="campus_public=.8",
        format="rehearsal performance tournament=.45",
        values="aesthetics tradition=.65 experience=.55 community=.7",
        environment="regular public team",
    ),
    "psychology_club": _profile(
        domain="psychology knowledge=.55",
        anchor="psychology_discussion",
        role="analyst facilitator=.45",
        audience="students=.45",
        format="club",
        values="learning community=.6 beginner=.55",
        environment="calm small_team",
    ),
    "resonance": _profile(
        domain="student_squad civic_history=.65",
        anchor="heritage_restoration",
        role="craft helper=.35",
        audience="campus_public=.3",
        format="summer_work field_activity=1",
        values="memory service=.55 responsibility=.75",
        environment="summer travel physical team",
    ),
    "gamma": _profile(
        domain="student_squad",
        anchor="train_conductor",
        role="helper speaker=.55",
        audience="people=1",
        format="summer_work shift_work=1",
        values="responsibility community=.65",
        environment="summer travel team public=.55",
    ),
    "hlam": _profile(
        domain="multidisciplinary_art performing_arts=.55",
        anchor="mixed_arts acting=.35 stage_production=.55",
        role="creator performer",
        audience="campus_public=.6",
        format="project rehearsal performance",
        values="exploration initiative community=.65 aesthetics=.6 beginner=.55",
        environment="regular public team",
    ),
    "nestor": _profile(
        domain="debate knowledge=.55 competition=.6",
        anchor="structured_debate",
        role="speaker analyst participant=.65",
        audience="students=.45",
        format="club tournament=.75",
        values="learning competition precision=.65",
        environment="small_team public=.65 competitive=.7",
    ),
    "deutschverein": _profile(
        domain="international knowledge=.55",
        anchor="german_language german_culture",
        role="speaker=.45 analyst=.25",
        audience="students=.5",
        format="club",
        values="learning community=.7 beginner=.65",
        environment="calm small_team",
    ),
    "friendship_club": _profile(
        domain="international social=.55",
        anchor="intercultural_exchange international_inclusion multicultural_event",
        role="facilitator mentor=.65 organizer=.75 speaker=.55",
        audience="international_students students=.55",
        format="large_event=.7 meetings=1",
        values="community service=.7 impact=.55",
        environment="project_based public=.65 team=.65",
    ),
    "sound_lab": _profile(
        domain="music",
        anchor="original_music instrumental=.55 vocal=.35",
        role="creator performer=.75",
        audience="campus_public=.55",
        format="project rehearsal performance=.65",
        values="initiative exploration=.6 community=.75",
        environment="regular team public=.45",
    ),
    "book_club": _profile(
        domain="literature knowledge=.65",
        anchor="book_discussion",
        role="analyst",
        audience="students=.35",
        format="club",
        values="learning community=.65 beginner=.55",
        environment="calm small_team regular=.55",
    ),
    "mephi_ball": _profile(
        domain="dance performing_arts=.55",
        anchor="themed_ball",
        role="organizer performer=.6 creator=.7",
        audience="campus_public",
        format="large_event rehearsal=.65 performance=.55",
        values="aesthetics tradition community=.7 initiative=.6",
        environment="seasonal_peak=1 public team=.75 project_based=.7",
    ),
    "pianists": _profile(
        domain="music",
        anchor="piano instrumental=.55",
        role="performer",
        audience="campus_public=.4",
        format="club rehearsal=.7 performance=.55",
        values="aesthetics learning=.6",
        environment="individual calm small_team=.55 public=.35",
    ),
    "board_games": _profile(
        domain="gaming competition=.45",
        anchor="tabletop_games",
        role="participant organizer=.45",
        audience="students=.45",
        format="club tournament=.75",
        values="community competition=.55 beginner=.7",
        environment="small_team flexible=.7 competitive=.45",
    ),
    "orchestra_mif": _profile(
        domain="music",
        anchor="orchestra instrumental=.7",
        role="performer",
        audience="campus_public=.75",
        format="rehearsal performance",
        values="aesthetics community=.8 experience=.55",
        environment="regular public team",
    ),
    "kraken": _profile(
        domain="student_squad",
        anchor="fishery_far_east",
        role="craft",
        audience="people=.2",
        format="summer_work shift_work=.8",
        values="responsibility community=.75 impact=.35",
        environment="summer travel physical team",
    ),
}


DISABLED_ORGANIZATION_IDS = frozenset({"pharaoh"})

_DIVERSITY_GROUP_MEMBERS: dict[str, str] = {
    "science": "sno",
    "media": "oso_press",
    "volunteer": "curators volunteer_center ecomephi",
    "sport": "reactor cyber_reactor",
    "self_government": "dorm_council starostat",
    "dance": "esta explosion paradox mephi_ball pharaoh",
    "music": "quanto carpe_diem male_choir sound_lab pianists orchestra_mif",
    "art": "vto izo poetry_club hlam",
    "clubs": "virm psychology_club nestor book_club board_games",
    "civic": "vernost",
    "student_squads": (
        "altavista mayak sleipnir energy_creators triumph resonance gamma kraken"
    ),
    "international": "deutschverein friendship_club",
}
ORGANIZATION_DIVERSITY_GROUP = {
    organization_id: group
    for group, organization_ids in _DIVERSITY_GROUP_MEMBERS.items()
    for organization_id in organization_ids.split()
}


def validate_matching_config(
    questions: Sequence[Mapping[str, Any]],
    organizations: Sequence[Mapping[str, Any]],
) -> None:
    if abs(sum(AXIS_BUDGETS.values()) - 100) > 1e-9:
        raise RuntimeError("Веса осей подбора должны давать 100")

    question_ids = {str(question["id"]) for question in questions}
    configured_question_ids = set(ANSWER_RULES)
    if question_ids != configured_question_ids:
        missing = sorted(question_ids - configured_question_ids)
        extra = sorted(configured_question_ids - question_ids)
        raise RuntimeError(
            f"Несовпадение вопросов и правил подбора: missing={missing}, extra={extra}"
        )

    for question in questions:
        question_id = str(question["id"])
        answer_ids = {str(answer["id"]) for answer in question["answers"]}
        configured_answer_ids = set(ANSWER_RULES[question_id])
        if answer_ids != configured_answer_ids:
            missing = sorted(answer_ids - configured_answer_ids)
            extra = sorted(configured_answer_ids - answer_ids)
            raise RuntimeError(
                "Несовпадение ответов и правил подбора для "
                f"{question_id}: missing={missing}, extra={extra}"
            )

    for question_rules in ANSWER_RULES.values():
        for rule in question_rules.values():
            for evidence in rule.evidence:
                if evidence.axis not in AXIS_BUDGETS:
                    raise RuntimeError(f"Неизвестная ось ответа: {evidence.axis}")
                if not -1 <= evidence.strength <= 1:
                    raise RuntimeError(f"Некорректная сила сигнала: {evidence}")

    organization_ids = {str(organization["id"]) for organization in organizations}
    configured_ids = set(ORGANIZATION_PROFILES) | set(DISABLED_ORGANIZATION_IDS)
    if organization_ids != configured_ids:
        missing = sorted(organization_ids - configured_ids)
        extra = sorted(configured_ids - organization_ids)
        raise RuntimeError(
            "Несовпадение объединений и профилей подбора: "
            f"missing={missing}, extra={extra}"
        )

    if organization_ids != set(ORGANIZATION_DIVERSITY_GROUP):
        missing = sorted(organization_ids - set(ORGANIZATION_DIVERSITY_GROUP))
        extra = sorted(set(ORGANIZATION_DIVERSITY_GROUP) - organization_ids)
        raise RuntimeError(
            "Несовпадение объединений и групп разнообразия: "
            f"missing={missing}, extra={extra}"
        )

    for organization_id, profile in ORGANIZATION_PROFILES.items():
        if not profile.facets.get("domain") or not profile.facets.get("anchor"):
            raise RuntimeError(f"У профиля {organization_id} нет domain или anchor")
        for axis, values in profile.facets.items():
            if axis not in AXIS_BUDGETS:
                raise RuntimeError(f"У профиля {organization_id} неизвестная ось {axis}")
            for value, affinity in values.items():
                if not value or not 0 <= affinity <= 1:
                    raise RuntimeError(
                        f"У профиля {organization_id} некорректен признак {axis}.{value}"
                    )


def _stable_tie_break(user_id: int, organization_id: str) -> int:
    digest = sha256(f"{user_id}:{organization_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _clean_answer_text(answer_text: str) -> str:
    parts = answer_text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0] and not parts[0][0].isalnum():
        return parts[1]
    return answer_text.strip()


def _aggregate_evidence(
    selected_answers: Mapping[str, str],
) -> dict[tuple[str, str], tuple[float, float]]:
    positive: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    negative: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for question_id, answer_id in selected_answers.items():
        for evidence in ANSWER_RULES[question_id][answer_id].evidence:
            target = positive if evidence.strength >= 0 else negative
            target[(evidence.axis, evidence.value)].append(abs(evidence.strength))

    keys = set(positive) | set(negative)
    return {
        key: (
            1 - prod(1 - strength for strength in positive.get(key, ())),
            1 - prod(1 - strength for strength in negative.get(key, ())),
        )
        for key in keys
    }


def _specificities() -> dict[tuple[str, str], float]:
    profile_count = len(ORGANIZATION_PROFILES)
    document_frequency: Counter[tuple[str, str]] = Counter(
        (axis, value)
        for profile in ORGANIZATION_PROFILES.values()
        for axis, values in profile.facets.items()
        for value, affinity in values.items()
        if affinity > 0
    )
    return {
        key: 0.25
        + 0.75
        * log((profile_count + 1) / (frequency + 1))
        / log(profile_count + 1)
        for key, frequency in document_frequency.items()
    }


FACET_SPECIFICITY = _specificities()


def _axis_match(
    axis: str,
    profile: OrganizationProfile,
    aggregated: Mapping[tuple[str, str], tuple[float, float]],
) -> tuple[float, float]:
    axis_evidence = [
        (value, positive, negative)
        for (evidence_axis, value), (positive, negative) in aggregated.items()
        if evidence_axis == axis
    ]
    if not axis_evidence:
        return 0.0, 0.0

    positive_weight = sum(
        positive * FACET_SPECIFICITY.get((axis, value), 0.9)
        for value, positive, _ in axis_evidence
    )
    negative_weight = sum(
        negative * FACET_SPECIFICITY.get((axis, value), 0.9)
        for value, _, negative in axis_evidence
    )
    support = (
        sum(
            positive
            * FACET_SPECIFICITY.get((axis, value), 0.9)
            * profile.affinity(axis, value)
            for value, positive, _ in axis_evidence
        )
        / positive_weight
        if positive_weight
        else 1.0
    )
    rejection = (
        sum(
            negative
            * FACET_SPECIFICITY.get((axis, value), 0.9)
            * profile.affinity(axis, value)
            for value, _, negative in axis_evidence
        )
        / negative_weight
        if negative_weight
        else 0.0
    )
    match = max(0.0, min(1.0, support - 1.25 * rejection))
    coverage = min(
        1.0,
        sum(
            max(positive, negative) * FACET_SPECIFICITY.get((axis, value), 0.9)
            for value, positive, negative in axis_evidence
        ),
    )
    return match, coverage


def _profile_is_hard_excluded(
    profile: OrganizationProfile,
    aggregated: Mapping[tuple[str, str], tuple[float, float]],
) -> bool:
    return any(
        axis in {"domain", "anchor"}
        and negative >= 0.85
        and profile.affinity(axis, value) >= 0.8
        for (axis, value), (_, negative) in aggregated.items()
    )


def _score_organization(
    organization: Mapping[str, Any],
    profile: OrganizationProfile,
    selected_answers: Mapping[str, str],
    aggregated: Mapping[tuple[str, str], tuple[float, float]],
    answer_texts: Mapping[tuple[str, str], str],
    question_order: Mapping[str, int],
    user_id: int,
) -> _Candidate:
    weighted_score = 0.0
    active_budget = 0.0
    axis_matches: dict[str, float] = {}
    for axis, budget in AXIS_BUDGETS.items():
        match, coverage = _axis_match(axis, profile, aggregated)
        axis_matches[axis] = match
        weighted_score += budget * coverage * match
        active_budget += budget * coverage

    base_score = 100 * weighted_score / active_budget if active_budget else 0.0
    anchor_positive_exists = any(
        axis == "anchor" and positive > 0
        for (axis, _), (positive, _) in aggregated.items()
    )
    anchor_support = axis_matches.get("anchor", 0.0) if anchor_positive_exists else 0.0
    if anchor_positive_exists:
        # Roles such as "organizer" may refine a recommendation, but a profile
        # without a thematic/activity anchor cannot win on that generic role.
        base_score *= 0.55 + 0.45 * anchor_support

    reason_candidates: list[tuple[float, int, str]] = []
    strong_matches = 0
    positive_matches = 0
    for question_id, answer_id in selected_answers.items():
        rule = ANSWER_RULES[question_id][answer_id]
        matched = [
            AXIS_BUDGETS[evidence.axis]
            * evidence.strength
            * profile.affinity(evidence.axis, evidence.value)
            for evidence in rule.evidence
            if evidence.strength > 0
        ]
        contribution = max(matched, default=0.0)
        if contribution <= 0:
            continue
        positive_matches += 1
        if any(
            evidence.axis == "anchor"
            and evidence.strength * profile.affinity(evidence.axis, evidence.value) >= 0.7
            for evidence in rule.evidence
        ):
            strong_matches += 1
        reason_candidates.append(
            (
                contribution,
                question_order[question_id],
                _clean_answer_text(answer_texts[(question_id, answer_id)]),
            )
        )

    reason_candidates.sort(key=lambda item: (-item[0], item[1]))
    reasons: list[str] = []
    for _, _, reason in reason_candidates:
        if reason not in reasons:
            reasons.append(reason)
        if len(reasons) == 2:
            break

    organization_id = str(organization["id"])
    return _Candidate(
        organization_id=organization_id,
        diversity_group=ORGANIZATION_DIVERSITY_GROUP[organization_id],
        family=profile.family,
        score=base_score,
        anchor_support=anchor_support,
        strong_matches=strong_matches,
        positive_matches=positive_matches,
        tie_break=_stable_tie_break(user_id, organization_id),
        reasons=tuple(reasons),
    )


def _candidate_key(candidate: _Candidate) -> tuple[float, float, int, int, int]:
    return (
        candidate.score,
        candidate.anchor_support,
        candidate.strong_matches,
        candidate.positive_matches,
        -candidate.tie_break,
    )


def _choose_results(candidates: Sequence[_Candidate]) -> list[_Candidate]:
    if not candidates:
        return []

    positive = [candidate for candidate in candidates if candidate.score > 0]
    pool = positive if len(positive) >= RESULT_COUNT else list(candidates)
    leader = max(pool, key=_candidate_key)
    relevance_floor = leader.score * 0.45

    selected: list[_Candidate] = []
    group_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    while len(selected) < min(RESULT_COUNT, len(pool)):
        remaining = [candidate for candidate in pool if candidate not in selected]
        relevant = [
            candidate for candidate in remaining if candidate.score >= relevance_floor
        ]
        eligible = relevant if relevant else remaining

        def utility(candidate: _Candidate) -> tuple[float, float, float, int, int, int]:
            family_penalty = (
                12 * family_counts[candidate.family]
                if candidate.family is not None
                else 0
            )
            group_penalty = 4 * group_counts[candidate.diversity_group]
            return (
                candidate.score - family_penalty - group_penalty,
                candidate.score,
                candidate.anchor_support,
                candidate.strong_matches,
                candidate.positive_matches,
                -candidate.tie_break,
            )

        chosen = max(eligible, key=utility)
        selected.append(chosen)
        group_counts[chosen.diversity_group] += 1
        if chosen.family is not None:
            family_counts[chosen.family] += 1

    return selected


def recommend_organizations(
    answers: Sequence[Mapping[str, str]],
    questions: Sequence[Mapping[str, Any]],
    organizations: Sequence[Mapping[str, Any]],
    *,
    user_id: int,
) -> tuple[MatchResult, ...]:
    selected_answers: dict[str, str] = {}
    for answer in answers:
        question_id = answer.get("question_id")
        answer_id = answer.get("answer_id")
        if not question_id or not answer_id:
            raise ValueError(
                "В сохранённом ответе отсутствует question_id или answer_id"
            )
        if question_id in selected_answers:
            raise ValueError(f"Вопрос {question_id} встречается в ответах дважды")
        selected_answers[str(question_id)] = str(answer_id)

    extra = sorted(set(selected_answers) - set(ANSWER_RULES))
    if extra:
        raise ValueError(f"В ответах есть неизвестные вопросы: extra={extra}")
    if not selected_answers:
        raise ValueError("Для подбора нужен хотя бы один ответ")

    for question_id, answer_id in selected_answers.items():
        if answer_id not in ANSWER_RULES[question_id]:
            raise ValueError(f"Неизвестный ответ {question_id}.{answer_id}")

    answer_texts = {
        (str(question["id"]), str(answer["id"])): str(answer["text"])
        for question in questions
        for answer in question["answers"]
    }
    question_order = {
        str(question["id"]): position
        for position, question in enumerate(questions)
    }
    aggregated = _aggregate_evidence(selected_answers)

    candidates = [
        _score_organization(
            organization,
            ORGANIZATION_PROFILES[str(organization["id"])],
            selected_answers,
            aggregated,
            answer_texts,
            question_order,
            user_id,
        )
        for organization in organizations
        if str(organization["id"]) not in DISABLED_ORGANIZATION_IDS
        and not _profile_is_hard_excluded(
            ORGANIZATION_PROFILES[str(organization["id"])],
            aggregated,
        )
    ]
    chosen = sorted(_choose_results(candidates), key=_candidate_key, reverse=True)

    return tuple(
        MatchResult(
            organization_id=candidate.organization_id,
            score=round(candidate.score, 3),
            reasons=candidate.reasons or ("Подходит по общему формату участия",),
        )
        for candidate in chosen
    )
