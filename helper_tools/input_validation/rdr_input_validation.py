# ---------------------------------------------------------------------------------------------------
# Name: rdr_input_validation
#
# Checks existence and contents of necessary input files for an RDR run.
# Does not check batch file, configuration file, or optional input files.
# User needs to provide the configuration file for the RDR run as an input argument.
#
# ---------------------------------------------------------------------------------------------------
import sys
import os
import argparse
import shutil
import subprocess
import logging
import sqlite3
import pandas as pd
import openmatrix as omx
from itertools import product

# Import modules from core code (two levels up) by setting path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'metamodel_py'))
import rdr_setup
import rdr_supporting
from rdr_LHS import check_model_params_coverage

VERSION_NUMBER = "2023.1"
VERSION_DATE = "04/10/2023"


def main():

    # ----------------------------------------------------------------------------------------------
    # PARSE ARGS
    program_description = 'Resilience Disaster Recovery Input Validation Helper Tool: ' \
                          + VERSION_NUMBER + ", (" + VERSION_DATE + ")"

    help_text = """
    The command-line input expected for this script is as follows:
    TheFilePathOfThisScript ConfigFilePath
    """

    parser = argparse.ArgumentParser(description=program_description, usage=help_text)

    parser.add_argument("config_file", help="The full path to the XML Scenario", type=str)

    if len(sys.argv) == 2:
        args = parser.parse_args()
    else:
        parser.print_help()
        sys.exit()

    # ---------------------------------------------------------------------------------------------------
    # SETUP
    cfg = rdr_setup.read_config_file(args.config_file)

    # Input files validated by this helper tool should be located in the scenario input directory
    input_folder = cfg['input_dir']

    # Logs and validation report will be put in the scenario output directory
    output_folder = cfg['output_dir']

    # Set up logging
    logger = rdr_supporting.create_loggers(output_folder, 'input_validation', cfg)

    logger.info("Starting input validation...")

    # Create list of input validation errors to put in a log file for users
    # If there is an error, it does not stop checking and just spits them all out at the end
    error_list = []

    # ---------------------------------------------------------------------------------------------------
    # Model_Parameters.xlsx
    # 1) Is it present
    # 2) Does it contain three tabs with required columns

    has_error_model_params = False
    has_error_resil_projects = False
    has_error_hazards = False

    model_params_file = os.path.join(input_folder, 'Model_Parameters.xlsx')
    # XLSX STEP 1: Check file exists
    if not os.path.exists(model_params_file):
        error_text = "MODEL PARAMETERS FILE ERROR: {} could not be found".format(model_params_file)
        logger.error(error_text)
        error_list.append(error_text)
        has_error_model_params = True
    else:
        # XLSX STEP 2: Check each tab exists
        try:
            model_params = pd.read_excel(model_params_file, sheet_name='UncertaintyParameters')
        except:
            error_text = "MODEL PARAMETERS FILE ERROR: UncertaintyParameters tab could not be found"
            logger.error(error_text)
            error_list.append(error_text)
            has_error_model_params = True
        else:
            # XLSX STEP 3: Check each tab has necessary columns
            try:
                model_params = pd.read_excel(model_params_file, sheet_name='UncertaintyParameters',
                                             converters={'Hazard Events': str, 'Recovery Stages': str,
                                                         'Economic Scenarios': str, 'Trip Loss Elasticities': str,
                                                         'Project Groups': str})
            except:
                error_text = "MODEL PARAMETERS FILE ERROR: UncertaintyParameters tab is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
                has_error_model_params = True
            else:
                # Test recovery stages are nonnegative numbers
                try:
                    recovery_num = pd.to_numeric(model_params['Recovery Stages'].dropna(), downcast='float')
                    assert(all(recovery_num >= 0))
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: Recovery stages are not all nonnegative numbers"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test elasticities can be converted to float
                try:
                    model_params['Trip Loss Elasticities'] = pd.to_numeric(model_params['Trip Loss Elasticities'].dropna(), downcast='float')
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: Elasticities could not be converted to float"
                    logger.error(error_text)
                    error_list.append(error_text)

                socio = set(model_params['Economic Scenarios'].dropna().tolist())
                projgroup = set(model_params['Project Groups'].dropna().tolist())
                elasticity = set(model_params['Trip Loss Elasticities'].dropna().tolist())
                hazard = set(model_params['Hazard Events'].dropna().tolist())
                recovery = set(model_params['Recovery Stages'].dropna().tolist())
            
        # XLSX STEP 2: Check each tab exists
        try:
            projgroup_to_resil = pd.read_excel(model_params_file, sheet_name='ProjectGroups')
        except:
            error_text = "MODEL PARAMETERS FILE ERROR: ProjectGroups tab could not be found"
            logger.error(error_text)
            error_list.append(error_text)
            has_error_resil_projects = True
        else:
            # XLSX STEP 3: Check each tab has necessary columns
            try:
                projgroup_to_resil = pd.read_excel(model_params_file, sheet_name='ProjectGroups',
                                                   converters={'Project Groups': str, 'Resiliency Projects': str})
            except:
                error_text = "MODEL PARAMETERS FILE ERROR: ProjectGroups tab is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
                has_error_resil_projects = True
            else:
                resil = set(projgroup_to_resil['Resiliency Projects'].dropna().tolist())

                # Confirm project groups are a subset of those listed in this tab
                if not has_error_model_params:
                    try:
                        assert(projgroup <= set(projgroup_to_resil['Project Groups'].dropna().tolist()))
                    except:
                        error_text = "MODEL PARAMETERS FILE ERROR: No resilience projects found for at least one project group"
                        logger.error(error_text)
                        error_list.append(error_text)

                # Confirm no resilience project is assigned to more than one project group
                try:
                    test_resil_projects = projgroup_to_resil.loc[projgroup_to_resil['Resiliency Projects'] != 'no',
                                                                 ['Project Groups', 'Resiliency Projects']].drop_duplicates(ignore_index=True)
                    assert(test_resil_projects.groupby(['Resiliency Projects']).size().max() == 1)
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: At least one resilience project assigned to multiple project groups"
                    logger.error(error_text)
                    error_list.append(error_text)

        # XLSX STEP 2: Check each tab exists
        try:
            hazard_events = pd.read_excel(model_params_file, sheet_name='Hazards')
        except:
            error_text = "MODEL PARAMETERS FILE ERROR: Hazards tab could not be found"
            logger.error(error_text)
            error_list.append(error_text)
            has_error_hazards = True
        else:
            # XLSX STEP 3: Check each tab has necessary columns
            try:
                hazard_events = pd.read_excel(model_params_file, sheet_name='Hazards',
                                              usecols=['Hazard Event', 'Filename', 'HazardDim1', 'HazardDim2', 'Event Probability in Start Year'],
                                              converters={'Hazard Event': str, 'Filename': str, 'HazardDim1': str, 'HazardDim2': str,
                                                          'Event Probability in Start Year': str})
            except:
                error_text = "MODEL PARAMETERS FILE ERROR: Hazards tab is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
                has_error_hazards = True
            else:
                # Test HazardDim1 can be converted to int
                try:
                    hazard_events['HazardDim1'] = pd.to_numeric(hazard_events['HazardDim1'], downcast='integer')
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: HazardDim1 column could not be converted to int"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test HazardDim2 can be converted to int
                try:
                    hazard_events['HazardDim2'] = pd.to_numeric(hazard_events['HazardDim2'], downcast='integer')
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: HazardDim2 column could not be converted to int"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test Event Probability in Start Year can be converted to float
                try:
                    hazard_events['Event Probability in Start Year'] = pd.to_numeric(hazard_events['Event Probability in Start Year'], downcast='float')
                except:
                    error_text = "MODEL PARAMETERS FILE ERROR: Event Probability in Start Year column could not be converted to float"
                    logger.error(error_text)
                    error_list.append(error_text)
                else:
                    if cfg['roi_analysis_type'] == 'Regret':
                        try:
                            assert(all(hazard_events['Event Probability in Start Year'] == 1.0))
                        except:
                            error_text = "MODEL PARAMETERS FILE ERROR: Event Probability in Start Year column must be set to 1 for regret analysis"
                            logger.error(error_text)
                            error_list.append(error_text)

                # Confirm hazards are a subset of those listed in this tab
                if not has_error_model_params:
                    try:
                        assert(hazard <= set(hazard_events['Hazard Event'].dropna().tolist()))
                    except:
                        error_text = "MODEL PARAMETERS FILE ERROR: No hazard row in Hazards tab found for at least one hazard event"
                        logger.error(error_text)
                        error_list.append(error_text)

                if not has_error_model_params:
                    hazards_list = pd.merge(pd.DataFrame(hazard, columns=['Hazard Event']),
                                            hazard_events, how='left', on='Hazard Event')
                else:
                    has_error_hazards = True

    # ---------------------------------------------------------------------------------------------------
    # UserInputs.xlsx
    # 1) Is it present
    # 2) Does it contain one tab with required columns
    # 3) Is every element of columns A-D of User Inputs file also an element of Model Parameters file
    user_inputs_file = os.path.join(input_folder, 'UserInputs.xlsx')

    # XLSX STEP 1: Check file exists
    if not os.path.exists(user_inputs_file):
        error_text = "USER INPUTS FILE ERROR: {} could not be found".format(user_inputs_file)
        logger.error(error_text)
        error_list.append(error_text)
    else:
        # XLSX STEP 2: Check each tab exists
        try:
            user_inputs = pd.read_excel(user_inputs_file, sheet_name='UserInputs')
        except:
            error_text = "USER INPUTS FILE ERROR: UserInputs tab could not be found"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            # XLSX STEP 3: Check each tab has necessary columns
            try:
                user_inputs = pd.read_excel(user_inputs_file, sheet_name='UserInputs',
                                            converters={'Hazard Events': str, 'Economic Scenarios': str,
                                                        'Trip Loss Elasticities': str, 'Resiliency Projects': str,
                                                        'Event Frequency Factors': str})
            except:
                error_text = "USER INPUTS FILE ERROR: UserInputs tab is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
            else:
                # Test elasticities can be converted to float
                try:
                    user_inputs['Trip Loss Elasticities'] = pd.to_numeric(user_inputs['Trip Loss Elasticities'].dropna(), downcast='float')
                except:
                    error_text = "USER INPUTS FILE ERROR: Elasticities could not be converted to float"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test event frequency factors are nonnegative numbers
                try:
                    event_frequency = pd.to_numeric(user_inputs['Event Frequency Factors'].dropna(), downcast='float')
                    assert(all(event_frequency >= 0))
                except:
                    error_text = "USER INPUTS FILE ERROR: Event frequency factors are not all nonnegative numbers"
                    logger.error(error_text)
                    error_list.append(error_text)

                if has_error_model_params:
                    error_text = "USER INPUTS FILE WARNING: Not comparing UserInputs.xlsx to Model_Parameters.xlsx, errors with Model_Parameters.xlsx"
                    logger.error(error_text)
                    error_list.append(error_text)
                else:
                    # Confirm user input parameters are a subset of those listed in model parameters file
                    try:
                        assert(set(user_inputs['Hazard Events'].dropna().tolist()) <= hazard)
                        assert(set(user_inputs['Economic Scenarios'].dropna().tolist()) <= socio)
                        assert(set(user_inputs['Trip Loss Elasticities'].dropna().tolist()) <= elasticity)
                        assert(set(user_inputs['Resiliency Projects'].dropna().tolist()) <= resil)
                    except:
                        error_text = "USER INPUTS FILE ERROR: List of parameters in user inputs file not a subset of model parameters file"
                        logger.error(error_text)
                        error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # Exposure analysis files
    # For each hazard listed in Model_Parameters.xlsx:
    # 1) Is there a hazard CSV file
    # 2) Check that link_id, A, B, Value (or similar) exist; link_id, A, B must be int, Value must be float
    hazard_folder = os.path.join(input_folder, 'Hazards')
    hazard_file_list = []
    if os.path.isdir(hazard_folder):
        for filename in os.listdir(hazard_folder):
            f = os.path.join(hazard_folder, filename)

            # Check if it is a file
            if os.path.isfile(f):
                hazard_file_list.append(filename)

        if has_error_hazards:
            error_text = "EXPOSURE ANALYSIS FILE WARNING: Not validating exposure analysis files, errors with Model_Parameters.xlsx"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            for index, row in hazards_list.iterrows():  # From Model_Parameters section
                h = str(row['Filename']) + '.csv'
                # CSV STEP 1: Check file exists
                if h not in hazard_file_list:
                    error_text = "EXPOSURE ANALYSIS FILE ERROR: No exposure analysis file is present for hazard {} listed in Model_Parameters.xlsx".format(row['Hazard Event'])
                    logger.error(error_text)
                    error_list.append(error_text)
                else:
                    # CSV STEP 2: Check file has necessary columns
                    try:
                        exposures = pd.read_csv(os.path.join(hazard_folder, h), usecols=['link_id', 'A', 'B', cfg['exposure_field']],
                                                converters={'link_id': str, 'A': str, 'B': str, cfg['exposure_field']: str})
                    except:
                        error_text = "EXPOSURE ANALYSIS FILE ERROR: File for hazard {} is missing required columns".format(row['Hazard Event'])
                        logger.error(error_text)
                        error_list.append(error_text)
                    else:
                        # Test link_id can be converted to int
                        try:
                            exposures['link_id'] = pd.to_numeric(exposures['link_id'], downcast='integer')
                        except:
                            error_text = "EXPOSURE ANALYSIS FILE ERROR: Column link_id could not be converted to int for hazard".format(row['Hazard Event'])
                            logger.error(error_text)
                            error_list.append(error_text)

                        # Test A can be converted to int
                        try:
                            exposures['A'] = pd.to_numeric(exposures['A'], downcast='integer')
                        except:
                            error_text = "EXPOSURE ANALYSIS FILE ERROR: Column A could not be converted to int for hazard".format(row['Hazard Event'])
                            logger.error(error_text)
                            error_list.append(error_text)

                        # Test B can be converted to int
                        try:
                            exposures['B'] = pd.to_numeric(exposures['B'], downcast='integer')
                        except:
                            error_text = "EXPOSURE ANALYSIS FILE ERROR: Column B could not be converted to int for hazard".format(row['Hazard Event'])
                            logger.error(error_text)
                            error_list.append(error_text)

                        # Test cfg['exposure_field'] can be converted to float
                        try:
                            exposures[cfg['exposure_field']] = pd.to_numeric(exposures[cfg['exposure_field']], downcast='float')
                        except:
                            error_text = "EXPOSURE ANALYSIS FILE ERROR: Column specifying exposure level could not be converted to float for hazard".format(row['Hazard Event'])
                            logger.error(error_text)
                            error_list.append(error_text)
    else:
        error_text = "EXPOSURE ANALYSIS FOLDER ERROR: Hazards directory for exposure analysis files does not exist"
        logger.error(error_text)
        error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # Network attribute files - link and node
    # 1) Is there a node CSV file
    # 2) Check that node_id, x_coord, y_coord, node_type exist; node_id must be int, x_coord, y_coord must be float
    # 3) Check that node_id has no duplicate values
    # For each socio and project group listed in Model_Parameters.xlsx:
    # 1) Is there a links CSV file
    # 2) Check that link_id, from_node_id, to_node_id, directed, length, facility_type, capacity, free_speed, lanes, allowed_uses, toll, travel_time exist;
    #    link_id, from_node_id, to_node_id, directed, lanes must be int, length, capacity, free_speed, toll, travel_time must be float
    # 3) Check that link_id has no duplicate values
    # 4) Check that directed is always 1, allowed_uses is always c
    # 5) If 'nocar' trip table matrix exists, check that toll_nocar, travel_time_nocar exist; both must be float
    networks_folder = os.path.join(input_folder, 'Networks')

    if os.path.isdir(networks_folder):
        # CSV STEP 1: Check file exists
        node_file = os.path.join(networks_folder, 'node.csv')
        if not os.path.exists(node_file):
            error_text = "NETWORK NODE FILE ERROR: Node input file could not be found"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            # CSV STEP 2: Check file has necessary columns
            try:
                nodes = pd.read_csv(node_file, usecols=['node_id', 'x_coord', 'y_coord', 'node_type'],
                                    converters={'node_id': str, 'x_coord': str, 'y_coord': str, 'node_type': str})
            except:
                error_text = "NETWORK NODE FILE ERROR: Node input file is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
            else:
                # Test node_id can be converted to int
                try:
                    nodes['node_id'] = pd.to_numeric(nodes['node_id'], downcast='integer')
                except:
                    error_text = "NETWORK NODE FILE ERROR: Column node_id could not be converted to int"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test node_id is a unique identifier
                try:
                    assert(not nodes.duplicated(subset=['node_id']).any())
                except:
                    error_text = "NETWORK NODE FILE ERROR: Column node_id is not a unique identifier"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test x_coord can be converted to float
                try:
                    nodes['x_coord'] = pd.to_numeric(nodes['x_coord'], downcast='float')
                except:
                    error_text = "NETWORK NODE FILE ERROR: Column x_coord could not be converted to float"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test y_coord can be converted to float
                try:
                    nodes['y_coord'] = pd.to_numeric(nodes['y_coord'], downcast='float')
                except:
                    error_text = "NETWORK NODE FILE ERROR: Column y_coord could not be converted to float"
                    logger.error(error_text)
                    error_list.append(error_text)

        links_file_list = []
        for filename in os.listdir(networks_folder):
            if filename != 'node.csv':
                f = os.path.join(networks_folder, filename)

                # Check if it is a file
                if os.path.isfile(f):
                    links_file_list.append(filename)

        if has_error_model_params:
            error_text = "NETWORK LINK FILE WARNING: Not validating network link files, errors with Model_Parameters.xlsx"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            for i in socio:
                for j in projgroup:
                    # CSV STEP 1: Check file exists
                    link_file = i + j + '.csv'
                    if link_file not in links_file_list:
                        error_text = "NETWORK LINK FILE ERROR: No network link file is present for socio {} and project group {} listed in Model_Parameters.xlsx".format(i, j)
                        logger.error(error_text)
                        error_list.append(error_text)
                    else:
                        # CSV STEP 2: Check file has necessary columns
                        try:
                            links = pd.read_csv(os.path.join(networks_folder, link_file),
                                                usecols=['link_id', 'from_node_id', 'to_node_id', 'directed', 'length', 'facility_type',
                                                         'capacity', 'free_speed', 'lanes', 'allowed_uses', 'toll', 'travel_time'],
                                                converters={'link_id': str, 'from_node_id': str, 'to_node_id': str, 'directed': str,
                                                            'length': str, 'facility_type': str, 'capacity': str, 'free_speed': str,
                                                            'lanes': str, 'allowed_uses': str, 'toll': str, 'travel_time': str})
                        except:
                            error_text = "NETWORK LINK FILE ERROR: File for socio {} and project group {} is missing required columns".format(i, j)
                            logger.error(error_text)
                            error_list.append(error_text)
                        else:
                            # Test link_id can be converted to int
                            try:
                                links['link_id'] = pd.to_numeric(links['link_id'], downcast='integer')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column link_id could not be converted to int for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test link_id is a unique identifier
                            try:
                                assert(not links.duplicated(subset=['link_id']).any())
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column link_id is not a unique identifier for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test from_node_id can be converted to int
                            try:
                                links['from_node_id'] = pd.to_numeric(links['from_node_id'], downcast='integer')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column from_node_id could not be converted to int for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test to_node_id can be converted to int
                            try:
                                links['to_node_id'] = pd.to_numeric(links['to_node_id'], downcast='integer')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column to_node_id could not be converted to int for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test directed can be converted to int and is always 1
                            try:
                                links['directed'] = pd.to_numeric(links['directed'], downcast='integer')
                                assert(all(links['directed'] == 1))
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column directed must have values of 1 only for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test lanes can be converted to int
                            try:
                                links['lanes'] = pd.to_numeric(links['lanes'], downcast='integer')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column lanes could not be converted to int for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test length can be converted to float
                            try:
                                links['length'] = pd.to_numeric(links['length'], downcast='float')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column length could not be converted to float for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test capacity can be converted to float
                            try:
                                links['capacity'] = pd.to_numeric(links['capacity'], downcast='float')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column capacity could not be converted to float for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test free_speed can be converted to float
                            try:
                                links['free_speed'] = pd.to_numeric(links['free_speed'], downcast='float')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column free_speed could not be converted to float for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test toll can be converted to float
                            try:
                                links['toll'] = pd.to_numeric(links['toll'], downcast='float')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column toll could not be converted to float for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test travel_time can be converted to float
                            try:
                                links['travel_time'] = pd.to_numeric(links['travel_time'], downcast='float')
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column travel_time could not be converted to float for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            # Test allowed_uses is always equal to 'c'
                            try:
                                assert(all(links['allowed_uses'] == 'c'))
                            except:
                                error_text = "NETWORK LINK FILE ERROR: Column allowed_uses must have values 'c' only for socio {} and project group {}".format(i, j)
                                logger.error(error_text)
                                error_list.append(error_text)

                            demand_folder = os.path.join(input_folder, 'AEMaster', 'matrices')
                            demand_file = i + '_demand_summed.omx'
                            if not os.path.exists(os.path.join(demand_folder, demand_file)):
                                error_text = "DEMAND FILE ERROR: No demand OMX file is present for socio {} corresponding to network link file {}".format(i, link_file)
                                logger.error(error_text)
                                error_list.append(error_text)
                            else:
                                omx_file = omx.open_file(os.path.join(demand_folder, demand_file))
                                if 'nocar' in omx_file.list_matrices():
                                    omx_file.close()
                                    try:
                                        links = pd.read_csv(os.path.join(networks_folder, link_file),
                                                usecols=['toll_nocar', 'travel_time_nocar'],
                                                converters={'toll': str, 'travel_time': str})
                                    except:
                                        error_text = "NETWORK LINK FILE ERROR: File for socio {} and project group {} is missing required columns corresponding to no car trip table".format(i, j)
                                        logger.error(error_text)
                                        error_list.append(error_text)
                                    else:
                                        # Test toll_nocar can be converted to float
                                        try:
                                            links['toll_nocar'] = pd.to_numeric(links['toll_nocar'], downcast='float')
                                        except:
                                            error_text = "NETWORK LINK FILE ERROR: Column toll_nocar could not be converted to float for socio {} and project group {}".format(i, j)
                                            logger.error(error_text)
                                            error_list.append(error_text)

                                        # Test travel_time_nocar can be converted to float
                                        try:
                                            links['travel_time_nocar'] = pd.to_numeric(links['travel_time_nocar'], downcast='float')
                                        except:
                                            error_text = "NETWORK LINK FILE ERROR: Column travel_time_nocar could not be converted to float for socio {} and project group {}".format(i, j)
                                            logger.error(error_text)
                                            error_list.append(error_text)

                                else:
                                    omx_file.close()
    else:
        error_text = "NETWORK FOLDER ERROR: Networks directory for network attribute files does not exist"
        logger.error(error_text)
        error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # Demand files
    # For each socio listed in Model_Parameters.xlsx:
    # 1) Is there a demand OMX file
    # 2) Check OMX file has 'matrix' square demand matrix and 'taz' mapping
    # 3) If 'nocar' trip table matrix, check that it is square
    demand_folder = os.path.join(input_folder, 'AEMaster', 'matrices')

    if os.path.isdir(demand_folder):
        demand_file_list = []
        for filename in os.listdir(demand_folder):
            f = os.path.join(demand_folder, filename)

            # Check if it is a file
            if os.path.isfile(f):
                demand_file_list.append(filename)

        if has_error_model_params:
            error_text = "DEMAND FILE WARNING: Not validating demand OMX files, errors with Model_Parameters.xlsx"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            for i in socio:
                # OMX STEP 1: Check file exists
                demand_file = i + '_demand_summed.omx'
                if demand_file not in demand_file_list:
                    error_text = "DEMAND FILE ERROR: No demand OMX file is present for socio {} listed in Model_Parameters.xlsx".format(i)
                    logger.error(error_text)
                    error_list.append(error_text)
                else:
                    try:
                        omx_file = omx.open_file(os.path.join(demand_folder, demand_file))
                        assert('matrix' in omx_file.list_matrices())
                        assert('taz' in omx_file.list_mappings())
                        matrix_shape = omx_file['matrix'].shape
                        assert(matrix_shape[0] == matrix_shape[1])
                    except:
                        error_text = "DEMAND FILE ERROR: OMX file is missing required attributes for socio {}".format(i)
                        logger.error(error_text)
                        error_list.append(error_text)
                    else:
                        if 'nocar' in omx_file.list_matrices():
                            try:
                                matrix_shape = omx_file['nocar'].shape
                                assert(matrix_shape[0] == matrix_shape[1])
                            except:
                                error_text = "DEMAND FILE ERROR: OMX file 'nocar' trip table is not square for socio {}".format(i)
                                logger.error(error_text)
                                error_list.append(error_text)
                        omx_file.close()
    else:
        error_text = "DEMAND FOLDER ERROR: Matrices directory for demand OMX files does not exist"
        logger.error(error_text)
        error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # SQLite database
    # 1) Is project_database.sqlite present in the AEMaster directory
    # 2) Check list of tables matches expected list of tables
    AEMaster_folder = os.path.join(input_folder, 'AEMaster')
    network_db_file = os.path.join(AEMaster_folder, 'project_database.sqlite')

    if not os.path.exists(network_db_file):
        error_text = "SQLite DATABASE FILE ERROR: {} could not be found".format(network_db_file)
        logger.error(error_text)
        error_list.append(error_text)
    else:
        with sqlite3.connect(network_db_file) as db_con:
            cur = db_con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            all_tables = cur.fetchall()
            nodes_exists = ('nodes',) in all_tables
            links_exists = ('links',) in all_tables

        if not nodes_exists:
            error_text = "SQLite DATABASE FILE ERROR: `nodes` table could not be found in {}".format(network_db_file)
            logger.error(error_text)
            error_list.append(error_text)

        if not links_exists:
            error_text = "SQLite DATABASE FILE ERROR: `links` table could not be found in {}".format(network_db_file)
            logger.error(error_text)
            error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # Base year core model runs file
    # 1) Is it present for the corresponding SP/RT outputs, Metamodel_scenario_SP_baseyear.csv OR Metamodel_scenario_RT_baseyear.csv
    # 2) Check that hazard, recovery, trips, miles, hours exist; recovery must be int, trips, miles, hours must be float
    baseyear_option = cfg['aeq_run_type']
    baseyear_files = []
    b_y = 'Metamodel_scenarios_' + baseyear_option + '_baseyear.csv'
    baseyear_files.append(os.path.join(input_folder, b_y))

    # CSV STEP 1: Check file exists
    any_baseyear_error = []
    for b_y in baseyear_files:
        any_baseyear_error.append(not os.path.exists(b_y))

    if all(any_baseyear_error):
        error_text = "BASE YEAR MODEL FILE ERROR: {} could not be found in {}".format(b_y, input_folder)
        logger.error(error_text)
        error_list.append(error_text)
    else:
        # CSV STEP 2: Check file has necessary columns
        # Read the first base year file available and verify columns
        try:
            baseyear = pd.read_csv(baseyear_files[0], usecols=['hazard', 'recovery', 'trips', 'miles', 'hours'],
                                   converters={'hazard': str, 'recovery': str, 'trips': str, 'miles': str, 'hours': str})
        except:
            error_text = "BASE YEAR MODEL FILE ERROR: Base year core model runs input file is missing required columns"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            # Test recovery stages are nonnegative numbers
            try:
                recovery_num = pd.to_numeric(baseyear['recovery'], downcast='float')
                assert(all(recovery_num >= 0))
            except:
                error_text = "BASE YEAR MODEL FILE ERROR: Recovery stages are not all nonnegative numbers"
                logger.error(error_text)
                error_list.append(error_text)

            # Test trips can be converted to float
            try:
                baseyear['trips'] = pd.to_numeric(baseyear['trips'], downcast='float')
            except:
                error_text = "BASE YEAR MODEL FILE ERROR: Column trips could not be converted to float"
                logger.error(error_text)
                error_list.append(error_text)

            # Test miles can be converted to float
            try:
                baseyear['miles'] = pd.to_numeric(baseyear['miles'], downcast='float')
            except:
                error_text = "BASE YEAR MODEL FILE ERROR: Column miles could not be converted to float"
                logger.error(error_text)
                error_list.append(error_text)

            # Test hours can be converted to float
            try:
                baseyear['hours'] = pd.to_numeric(baseyear['hours'], downcast='float')
            except:
                error_text = "BASE YEAR MODEL FILE ERROR: Column hours could not be converted to float"
                logger.error(error_text)
                error_list.append(error_text)

            # Test hazard-recovery pairs can be found for every pair in Model_Parameters.xlsx
            try:
                hazard_b_y = set(baseyear['hazard'].dropna().tolist())
                recovery_b_y = set(baseyear['recovery'].dropna().tolist())
                product_m_p = set(list(product(hazard, recovery)))
                product_b_y = set(list(product(hazard_b_y, recovery_b_y)))
                assert(product_m_p <= product_b_y)
            except:
                error_text = "BASE YEAR MODEL FILE ERROR: Base year core model runs input file is missing at least one hazard-recovery combination"
                logger.error(error_text)
                error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # Resilience projects files
    # 1) Are project_info.csv and project_table.csv files present
    # 2) Check that project_info.csv has columns Project ID, Project Name, Asset, Project Cost, Project Lifespan, Annual Maintenance Cost; Project Cost and Annual Maintenance Cost should be converted to dollar
    # 3) Check that project_table.csv has columns link_id, Project ID, Category; link_id must be int, Exposure Reduction must be float if exists
    resil_folder = os.path.join(input_folder, 'LookupTables')

    if os.path.isdir(resil_folder):
        # CSV STEP 1: Check file exists
        project_info_file = os.path.join(resil_folder, 'project_info.csv')
        if not os.path.exists(project_info_file):
            error_text = "RESILIENCE PROJECTS FILE ERROR: Project info input file could not be found"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            # CSV STEP 2: Check file has necessary columns
            try:
                project_info = pd.read_csv(project_info_file, usecols=['Project ID', 'Project Name', 'Asset', 'Project Cost',
                                                                       'Project Lifespan', 'Annual Maintenance Cost'],
                                           converters={'Project ID': str, 'Project Name': str, 'Asset': str, 'Project Cost': str,
                                                       'Project Lifespan': str, 'Annual Maintenance Cost': str})
            except:
                error_text = "RESILIENCE PROJECTS FILE ERROR: Project info input file is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
            else:
                # Test Project Cost can be converted to dollar amount
                try:
                    project_cost = project_info['Project Cost'].replace('[\$,]', '', regex=True).astype(float)
                except:
                    error_text = "RESILIENCE PROJECTS FILE ERROR: Column Project Cost could not be translated to dollar amount in project info input file"
                    logger.error(error_text)
                    error_list.append(error_text)
                else:
                    if cfg['roi_analysis_type'] == 'Breakeven':
                        try:
                            assert(all(project_cost == 0))
                        except:
                            error_text = "RESILIENCE PROJECTS FILE ERROR: For breakeven analysis, Project Cost should be set to zero in project info input file"
                            logger.error(error_text)
                            error_list.append(error_text)

                # Test Project Lifespan can be converted to int
                try:
                    project_info['Project Lifespan'] = pd.to_numeric(project_info['Project Lifespan'], downcast='integer')
                    assert(all(project_info['Project Lifespan'] >= 0))
                except:
                    error_text = "RESILIENCE PROJECTS FILE ERROR: Column Project Lifespan could not be converted to positive integers in project info input file"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test Annual Maintenance Cost can be converted to dollar amount
                try:
                    project_cost = project_info['Annual Maintenance Cost'].replace('[\$,]', '', regex=True).astype(float)
                except:
                    error_text = "RESILIENCE PROJECTS FILE ERROR: Column Annual Maintenance Cost could not be translated to dollar amount in project info input file"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Confirm resilience projects are a subset of those listed in this input file
                if not has_error_resil_projects:
                    try:
                        assert(resil <= set(project_info['Project ID'].dropna().tolist()))
                    except:
                        error_text = "RESILIENCE PROJECTS FILE ERROR: Missing resilience projects in project info input file"
                        logger.error(error_text)
                        error_list.append(error_text)

        # CSV STEP 1: Check file exists
        project_table_file = os.path.join(resil_folder, 'project_table.csv')
        if not os.path.exists(project_table_file):
            error_text = "RESILIENCE PROJECTS FILE ERROR: Project table input file could not be found"
            logger.error(error_text)
            error_list.append(error_text)
        else:
            # CSV STEP 2: Check file has necessary columns
            try:
                resil_mitigation_approach = cfg['resil_mitigation_approach']
                if resil_mitigation_approach == 'binary':
                    project_table = pd.read_csv(project_table_file, usecols=['Project ID', 'link_id', 'Category'],
                                                converters={'Project ID': str, 'link_id': str, 'Category': str})
                    # NOTE: use 99999 to create dummy Exposure Reduction column
                    project_table['Exposure Reduction'] = 99999.0
                elif resil_mitigation_approach == 'manual':
                    project_table = pd.read_csv(project_table_file, usecols=['Project ID', 'link_id', 'Category', 'Exposure Reduction'],
                                                converters={'Project ID': str, 'link_id': str, 'Category': str, 'Exposure Reduction': str})
            except:
                error_text = "RESILIENCE PROJECTS FILE ERROR: Project table input file is missing required columns"
                logger.error(error_text)
                error_list.append(error_text)
            else:
                # Test link_id can be converted to int
                try:
                    project_table['link_id'] = pd.to_numeric(project_table['link_id'], downcast='integer')
                except:
                    error_text = "RESILIENCE PROJECTS FILE ERROR: Column link_id could not be converted to int in project table input file"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Test Exposure Reduction can be converted to float
                try:
                    project_table['Exposure Reduction'] = pd.to_numeric(project_table['Exposure Reduction'], downcast='float')
                except:
                    error_text = "RESILIENCE PROJECTS FILE ERROR: Column Exposure Reduction could not be converted to float in project table input file"
                    logger.error(error_text)
                    error_list.append(error_text)

                # Confirm Category is either 'Highway', 'Bridge', or 'Transit' if using default repair tables
                if cfg['repair_cost_approach'] == 'Default' or cfg['repair_time_approach'] == 'Default':
                    try:
                        assert(all(project_table['Category'].isin(['Highway', 'Bridge', 'Transit'])))
                    except:
                        error_text = "RESILIENCE PROJECTS FILE ERROR: Category values in project table input file must be 'Highway', 'Bridge', or 'Transit' if using default repair tables"
                        logger.error(error_text)
                        error_list.append(error_text)
    else:
        error_text = "RESILIENCE PROJECTS FOLDER ERROR: LookupTables directory for resilience projects files does not exist"
        logger.error(error_text)
        error_list.append(error_text)

    # ---------------------------------------------------------------------------------------------------
    # LAST STEPS
    # If any check failed, raise exception
    if len(error_list)> 0:
        raise Exception("Exiting script with {} breaking errors found! See logger.error outputs in log file for details. Consult the Run Checklist and User Guide to fix.".format(len(error_list)))
    else:
        logger.info("All input validation checks passed successfully! No errors found.")
    
    return


# ---------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()