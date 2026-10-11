from platforms.indeed.indeed_agent import IndeedAgent


def test_native_semantic_tel_attributes_route_phone_without_label():
    assert IndeedAgent._native_profile_semantic('', 'contact_number', '', '', '', '', 'tel', 'tel', '') == 'phone'


def test_native_semantic_autocomplete_tel_routes_phone():
    assert IndeedAgent._native_profile_semantic('', '', '', '', '', 'tel', '', '', '') == 'phone'


def test_native_semantic_email_type_alone_does_not_route_narrative():
    assert IndeedAgent._native_profile_semantic('Message', 'Contact-Message-Field-01', 'Contact-Message-Field-01', '', '', '', 'email', '', '') is None


def test_native_semantic_explicit_email_still_routes_email():
    assert IndeedAgent._native_profile_semantic('Email address *', 'email', '', '', '', 'email', 'email', '', '') == 'email'


def test_native_semantic_autocomplete_city_and_postal():
    assert IndeedAgent._native_profile_semantic('', '', '', '', '', 'address-level2', '', '', '') == 'city'
    assert IndeedAgent._native_profile_semantic('', '', '', '', '', 'postal-code', '', '', '') == 'pin_code'
